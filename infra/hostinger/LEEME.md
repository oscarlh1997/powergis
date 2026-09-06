# Subir el motor a un VPS de Hostinger

WordPress se queda donde está (hosting compartido, `powergis.es`). Aquí sólo va
el motor, en `motor.powergis.es`. Se hablan por HTTPS con firma HMAC.

## 0. El registro DNS, antes que nada

Traefik pide el certificado por desafío HTTP en cuanto arranca. Si el DNS no
resuelve todavía, el desafío falla y **Let's Encrypt limita los reintentos por
dominio**: te puedes quedar una hora sin poder pedirlo.

En hPanel → *Dominios → powergis.es → DNS / Nameservers*:

    Tipo   Nombre   Valor            TTL
    A      motor    <IP del VPS>     300

Y espera a que responda:

    dig +short motor.powergis.es          # o Resolve-DnsName en PowerShell

No hace falta cambiar servidores de nombres: el DNS de powergis.es ya está en
Hostinger. Y **no crees un registro `AAAA`** salvo que hayas configurado IPv6
en Docker: Let's Encrypt lo preferiría y el desafío no llegaría.

## 1. Tu clave SSH en el servidor

Desde PowerShell, en tu Windows:

```powershell
# sólo si aún no tienes clave
ssh-keygen -t ed25519 -C powergis

scp $env:USERPROFILE\.ssh\id_ed25519.pub root@TU_IP:/tmp/clave.pub
```

## 2. Endurecer la máquina

```powershell
scp infra\hostinger\preparar-vps.sh root@TU_IP:/root/
ssh root@TU_IP
```

Ya dentro:

```bash
mkdir -p /home/powergis/.ssh
cat /tmp/clave.pub >> /root/.ssh/authorized_keys
bash /root/preparar-vps.sh
```

Deja usuario sin privilegios, SSH sólo por clave, `ufw`, swap, Docker y el
reloj sincronizado. **Se niega a desactivar las contraseñas si no encuentra
ninguna clave pública instalada**, para que no te quedes fuera.

Antes de cerrar esa sesión, abre otra ventana y comprueba que `ssh
powergis@TU_IP` entra. Si algo salió mal, esa primera sesión es tu forma de
arreglarlo — y la consola web de Hostinger, la segunda.

## 3. Subir el código

Hay cuatro vías. La primera es la recomendada; las otras están por si esa
falla o prefieres otra cosa.

### A · `subir.ps1` — un comando, repetible

```powershell
cd C:\Users\oscar\Downloads\powergis-backend\powergis
.\infra\hostinger\subir.ps1 -Ip TU_IP
```

Empaqueta con `tar`, sube por `scp` y descomprime en `~/powergis`. Pensado
para repetirlo cada vez que cambie algo.

**No incluye el `.env`**, así que descomprimir encima nunca se lleva por
delante los secretos del servidor. Y comprueba antes de subir que el paquete
conserva las rutas: `Compress-Archive` las aplana cuando se le pasa una lista
de ficheros, y `engine/src/powergis/cli.py` llegaría como `cli.py` en la raíz.

Antes de haber ejecutado `preparar-vps.sh` todavía no existe el usuario
`powergis`, así que la primera vez:

```powershell
.\infra\hostinger\subir.ps1 -Ip TU_IP -Usuario root
```

### B · WinSCP o FileZilla — si prefieres arrastrar y soltar

Protocolo **SFTP**, puerto 22, con tu usuario y tu clave SSH (en FileZilla:
*Editar → Opciones → SFTP → Añadir archivo de claves*). Arrastras la carpeta a
`/home/powergis/powergis` y listo.

Más lento —son miles de ficheros pequeños, y SFTP negocia cada uno— pero no
hay que aprender ningún comando. **Cuidado con no arrastrar tu `.env` local
encima del del servidor.**

### C · La terminal del navegador de Hostinger

En el panel del VPS hay una consola web. No permite subir ficheros, pero sí
descargar desde una URL, así que sirve como salida de emergencia si tu ISP o
tu red bloquean el puerto 22.

También te salva si te quedas sin acceso SSH: es la única vía que no depende
de la clave.

### D · Git — la recomendada

El repositorio ya viene inicializado y con el primer commit hecho. Historial
de qué cambió y cuándo, vuelta atrás inmediata si un despliegue rompe algo, y
deja de depender de que tu portátil tenga la última copia.

#### D.1 · Crear el repositorio en GitHub

Créalo **privado** y **vacío** —sin README, sin `.gitignore`, sin licencia—,
porque este repositorio ya los trae y un repositorio no vacío obliga a
fusionar antes del primer push.

```powershell
cd C:\Users\oscar\Downloads\powergis-backend\powergis

git remote add origin git@github.com:TU_USUARIO/powergis.git
git branch -M main
git push -u origin main
```

Si prefieres HTTPS en vez de SSH, la URL es
`https://github.com/TU_USUARIO/powergis.git` y GitHub te pedirá un token
personal en vez de la contraseña.

Comprueba antes de empujar que no viaja nada que no deba:

```powershell
git status
git log --stat -1 | Select-String "\.env"     # no debe devolver nada
```

#### D.2 · La clave de despliegue del VPS

El servidor necesita poder leer el repositorio, y **sólo leer**. Una clave de
despliegue hace justo eso: vale para un único repositorio, es de sólo lectura,
y no da acceso al resto de tu cuenta de GitHub. No uses tu clave personal.

```bash
# en el VPS
ssh-keygen -t ed25519 -C "vps-powergis" -f ~/.ssh/github -N ""
cat ~/.ssh/github.pub
```

En GitHub: **Settings del repositorio → Deploy keys → Add deploy key**. Pega
esa línea. **Deja «Allow write access» sin marcar.**

Y dile a SSH que use esa clave para GitHub:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/github
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

ssh -T git@github.com     # "Hi TU_USUARIO/powergis! You've successfully authenticated"
```

#### D.3 · Clonar y arrancar

```bash
git clone git@github.com:TU_USUARIO/powergis.git ~/powergis
cd ~/powergis
cp .env.example .env
nano .env
make check-config
make up
```

#### D.4 · Cada despliegue posterior

En tu Windows, un commit y un push:

```powershell
git add -A
git commit -m "lo que has cambiado"
git push
```

En el VPS, un comando:

```bash
~/powergis/infra/hostinger/desplegar.sh
```

Trae los cambios, reconstruye lo que haga falta y deja el stack en marcha.
Te enseña qué commits entraron. **No toca el `.env` ni los volúmenes**: la
base de datos y los certificados sobreviven a cualquier despliegue. Y se
niega a continuar si detecta cambios locales sin confirmar en el servidor,
para no pisarlos.

> **Lo que no sube nunca:** el `.env`. Está en `.gitignore`. Los secretos
> viven en el VPS y en `wp-config.php`, en ningún otro sitio.
>
> Las credenciales que verás en `docker-compose.dev.yml` y en el CI son de
> desarrollo y están ahí a propósito: sirven para levantar el entorno local
> sin configurar nada. No valen para producción y el motor se niega a
> arrancar con ellas si `ENV=production`.

### Lo que NO sirve

- **El administrador de archivos de hPanel** es para el hosting compartido,
  no para el VPS. Son máquinas distintas.
- **El catálogo de aplicaciones / n8n / Docker Manager** del panel instala
  aplicaciones preempaquetadas. Tu stack ya viene definido en
  `docker-compose.yml`; instalar algo desde ahí solo añadiría servicios que
  competirían por los puertos 80 y 443.

## 4. Configuración

```bash
cp .env.example .env
openssl rand -hex 32     # HMAC_SECRET
openssl rand -hex 32     # INTERNAL_API_KEY
openssl rand -hex 24     # POSTGRES_PASSWORD
nano .env
```

Lo que hay que tocar sí o sí:

| Variable | Valor |
|---|---|
| `ENV` | `production` |
| `DEBUG` | `false` |
| `ENGINE_HOST` | `motor.powergis.es` |
| `ACME_EMAIL` | tu correo |
| `POSTGRES_PASSWORD` | el generado |
| `DATABASE_URL` | **con esa misma contraseña dentro** |
| `HMAC_SECRET` | el generado — idéntico al de `wp-config.php` |
| `INTERNAL_API_KEY` | el generado |
| `ALLOWED_ORIGINS` | `https://powergis.es,https://www.powergis.es` |
| `WORDPRESS_BASE_URL` | `https://powergis.es` |
| `LLM_ENABLED` | `false` por ahora |

`DATABASE_URL` es el que se olvida siempre: lleva la contraseña embebida y hay
que cambiarla en los dos sitios.

**No reutilices `guachineatata2026kimbapaquesuene`.** Ha circulado por el
repositorio y por nuestras conversaciones: dalo por comprometido.

## 5. Levantar

```bash
make check-config     # valida el .env sin levantar nada
make up               # KVM 2 es el perfil por defecto
make ps
```

La primera vez tarda: construye la imagen del motor.

Comprobaciones:

```bash
curl -i https://motor.powergis.es/health              # 200, con certificado válido
curl -i https://motor.powergis.es/internal/coverage   # 403
curl -i https://motor.powergis.es/ready               # 503 todavía: falta migrar
```

## 6. El almacén

```bash
make almacen          # migraciones + catálogo + geografías + ~8.100 municipios
make ine-verify       # comprueba el mapeo del INE ANTES de cargar
make ingest-ine       # carga el Padrón (tarda)
make derive
make smoke
```

Ahora `/ready` sí devuelve 200.

## 7. Enganchar WordPress

En el `wp-config.php` de powergis.es, por encima de
`/* That's all, stop editing! */`:

```php
define( 'POWERGIS_ENGINE_URL',  'https://motor.powergis.es' );
define( 'POWERGIS_HMAC_SECRET', '…el mismo HMAC_SECRET del .env…' );
define( 'POWERGIS_CALLBACK_URL', 'https://powergis.es/wp-json/saas/v1/projects/callback' );
```

`POWERGIS_DEV_MODE` **no se define aquí jamás**: activa el simulador de pago y
cualquiera desbloquearía informes de pago gratis.

Comprueba en *Proyectos → Diagnóstico* que «Motor accesible» da `HTTP 200`.
Esa fila también te confirma que tu hosting compartido permite llamadas HTTPS
salientes desde PHP.

## Si algo falla

| Síntoma | Causa más probable |
|---|---|
| Contenedores en bucle de reinicio | Configuración inválida: `make logs` lo dice. `make check-config` |
| 401 `invalid_signature` | Secretos distintos, o relojes separados >5 min (`timedatectl`) |
| `/health` 200 pero nada va | `/health` es liveness a propósito; mira `/ready` |
| 404 al buscar una zona | `dim_geo` vacía: se ejecutó `bootstrap` y no `almacen` |
| El certificado no se emite | El DNS no resolvía cuando Traefik lo pidió |

`make diagnostico` vuelca el estado completo a un fichero.
