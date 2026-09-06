#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PowerGIS · dejar listo un VPS de Hostinger recién creado
#
# Hace lo mismo que el `cloud-init.yaml` de la carpeta hermana, pero para una
# máquina que YA existe: cuando se crea desde el panel de Hostinger no hay
# ocasión de pasarle user-data.
#
#     scp infra/hostinger/preparar-vps.sh root@TU_IP:/root/
#     ssh root@TU_IP
#     bash /root/preparar-vps.sh
#
# Qué deja hecho:
#   · usuario `powergis` sin contraseña, con tu clave pública
#   · SSH sin root y sin contraseñas, por drop-in (ver más abajo)
#   · ufw con 22, 80 y 443 y nada más
#   · fail2ban y actualizaciones de seguridad automáticas
#   · swap de 2 GB con swappiness bajo
#   · Docker
#   · reloj sincronizado por NTP
#
# Es idempotente: se puede volver a ejecutar sin romper nada.
# ---------------------------------------------------------------------------
set -euo pipefail

USUARIO="${USUARIO:-powergis}"
ZONA="${ZONA:-Europe/Madrid}"

azul()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()    { printf '   \033[0;32mok\033[0m  %s\n' "$*"; }
aviso() { printf '   \033[0;33m!!\033[0m  %s\n' "$*"; }
morir() { printf '\n\033[0;31mABORTADO: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || morir "ejecútalo como root"

# ---------------------------------------------------------------------------
# 1. Usuario
# ---------------------------------------------------------------------------
azul "Usuario $USUARIO"
if id "$USUARIO" >/dev/null 2>&1; then
	ok "ya existía"
else
	adduser --disabled-password --gecos "" "$USUARIO"
	ok "creado"
fi
usermod -aG sudo "$USUARIO"
echo "$USUARIO ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$USUARIO"
chmod 440 "/etc/sudoers.d/90-$USUARIO"
ok "sudo sin contraseña"

# Copiar las claves que Hostinger haya puesto en root.
mkdir -p "/home/$USUARIO/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
	cat /root/.ssh/authorized_keys >> "/home/$USUARIO/.ssh/authorized_keys"
	# Sin duplicados si se ejecuta dos veces.
	sort -u "/home/$USUARIO/.ssh/authorized_keys" -o "/home/$USUARIO/.ssh/authorized_keys"
fi
chown -R "$USUARIO:$USUARIO" "/home/$USUARIO/.ssh"
chmod 700 "/home/$USUARIO/.ssh"
touch "/home/$USUARIO/.ssh/authorized_keys"
chmod 600 "/home/$USUARIO/.ssh/authorized_keys"

CLAVES=$(grep -c '^ssh-' "/home/$USUARIO/.ssh/authorized_keys" 2>/dev/null || echo 0)

# ---------------------------------------------------------------------------
# 2. Paquetes
# ---------------------------------------------------------------------------
azul "Paquetes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ufw fail2ban unattended-upgrades ca-certificates curl git make jq >/dev/null
ok "instalados"

# ---------------------------------------------------------------------------
# 3. Swap
# ---------------------------------------------------------------------------
# Con 8 GB y PostgreSQL dentro, el peor final posible es que el kernel elija
# matar la base de datos en un pico. `swappiness` bajo para que el swap sea el
# seguro y no la rutina.
azul "Swap de 2 GB"
if swapon --show | grep -q '/swapfile'; then
	ok "ya activo"
else
	fallocate -l 2G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
	ok "creado y montado"
fi
cat > /etc/sysctl.d/99-powergis.conf <<'EOF'
vm.swappiness = 10
vm.overcommit_memory = 1
net.core.somaxconn = 1024
EOF
sysctl --system >/dev/null
ok "swappiness a 10"

# ---------------------------------------------------------------------------
# 4. Reloj
# ---------------------------------------------------------------------------
# No es cosmético: la firma HMAC lleva marca de tiempo y el motor rechaza todo
# lo que caiga fuera de una ventana de 300 s. Si este reloj y el del hosting
# de WordPress se separan más de cinco minutos, TODO devuelve 401
# invalid_signature y parece un problema de secretos.
azul "Reloj"
timedatectl set-ntp true || true
timedatectl set-timezone "$ZONA" || true
ok "$(timedatectl show -p Timezone --value) · NTP $(timedatectl show -p NTPSynchronized --value)"

# ---------------------------------------------------------------------------
# 5. Cortafuegos
# ---------------------------------------------------------------------------
azul "Cortafuegos"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ok "22, 80 y 443. PostgreSQL y Redis nunca publican puerto."

cat > /etc/fail2ban/jail.d/powergis.conf <<'EOF'
[sshd]
enabled  = true
port     = ssh
maxretry = 3
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 || true
ok "fail2ban"

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
ok "actualizaciones de seguridad automáticas"

# ---------------------------------------------------------------------------
# 6. Docker
# ---------------------------------------------------------------------------
azul "Docker"
#
# El script oficial (get.docker.com) tarda meses en reconocer cada versión
# nueva de Ubuntu y aborta con «unsupported distribution». Este VPS viene con
# 26.04 LTS, así que hay que contar con ello: si falla, se añade el
# repositorio a mano y, si tampoco existe para este nombre en clave, se usa el
# del LTS anterior (`noble`, 24.04). Los paquetes son compatibles; lo único
# que falta en el repositorio nuevo es la carpeta, no el software.
instalar_docker_desde_repo() {
	local clave
	clave="$(. /etc/os-release && echo "${VERSION_CODENAME:-noble}")"

	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
		-o /etc/apt/keyrings/docker.asc
	chmod a+r /etc/apt/keyrings/docker.asc

	# ¿Existe el repositorio para este nombre en clave?
	if ! curl -fsI "https://download.docker.com/linux/ubuntu/dists/${clave}/Release" >/dev/null 2>&1; then
		aviso "Docker aún no publica repositorio para '${clave}'; uso 'noble' (24.04 LTS)"
		clave="noble"
	fi

	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${clave} stable" \
		> /etc/apt/sources.list.d/docker.list

	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin >/dev/null
}

if command -v docker >/dev/null 2>&1; then
	ok "ya estaba instalado"
else
	if curl -fsSL https://get.docker.com | sh >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
		ok "instalado con el script oficial"
	else
		aviso "el script oficial no soportó esta versión de Ubuntu; voy por el repositorio"
		instalar_docker_desde_repo
		command -v docker >/dev/null 2>&1 || morir "no he podido instalar Docker"
		ok "instalado desde el repositorio de Docker"
	fi
fi

# `docker compose` (v2, plugin) es lo que usan el Makefile y los ficheros del
# proyecto. Sin él, `make up` falla con «unknown command: compose».
docker compose version >/dev/null 2>&1 \
	|| apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 \
	|| aviso "revisa que 'docker compose version' funcione antes de 'make up'"
systemctl enable --now docker >/dev/null 2>&1 || true
usermod -aG docker "$USUARIO"
# Sin esto, un contenedor hablador llena el disco.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl restart docker
ok "rotación de logs configurada"

# ---------------------------------------------------------------------------
# 7. SSH — lo último, y sólo si no te deja fuera
# ---------------------------------------------------------------------------
azul "SSH"
if [ "$CLAVES" -eq 0 ]; then
	aviso "NO voy a desactivar las contraseñas: $USUARIO no tiene ninguna clave"
	aviso "pública instalada y te quedarías fuera de tu propio servidor."
	echo
	echo "   Desde tu Windows, en PowerShell:"
	echo
	echo "     ssh-keygen -t ed25519 -C powergis      # si aún no tienes clave"
	echo "     scp \$env:USERPROFILE\\.ssh\\id_ed25519.pub root@$(hostname -I | awk '{print $1}'):/tmp/clave.pub"
	echo "     ssh root@$(hostname -I | awk '{print $1}') \"cat /tmp/clave.pub >> /home/$USUARIO/.ssh/authorized_keys && rm /tmp/clave.pub\""
	echo
	echo "   Y vuelve a lanzar este script. Todo lo demás ya está hecho."
	exit 0
fi

# Las imágenes de Ubuntu traen /etc/ssh/sshd_config.d/50-cloud-init.conf, y los
# ficheros de ese directorio GANAN sobre sshd_config. Editar el principal —que
# es lo que dice casi toda guía— deja la contraseña activada y la máquina
# parece endurecida sin estarlo. Este drop-in ordena después y tiene la última
# palabra.
cat > /etc/ssh/sshd_config.d/99-powergis.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
EOF

sshd -t || morir "la configuración de SSH no es válida; no la aplico"
systemctl restart ssh || systemctl restart sshd
ok "$CLAVES clave(s) instaladas · root y contraseñas desactivados"

IP=$(hostname -I | awk '{print $1}')
cat <<FIN

──────────────────────────────────────────────────────────────
 Listo.

 ANTES DE CERRAR ESTA SESIÓN, abre otra ventana y comprueba:

     ssh $USUARIO@$IP

 Si no entras, arréglalo desde aquí. Esta sesión es tu red de
 seguridad —y el navegador de Hostinger, la segunda.

 Comprobaciones:
     sshd -T | grep -E 'permitrootlogin|passwordauthentication'
     ufw status
     swapon --show
     timedatectl
     sudo -u $USUARIO docker run --rm hello-world
──────────────────────────────────────────────────────────────
FIN
