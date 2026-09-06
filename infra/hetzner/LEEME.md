# Desplegar en Hetzner Cloud

Todo lo que cambia respecto a Hostinger está en esta carpeta y en dos ficheros
de override. El motor no cambia: es el mismo código y el mismo
`docker-compose.yml`.

## Qué hay aquí

    cloud-init.yaml       endurece la máquina en el PRIMER arranque
    crear-servidor.sh     crea firewall + servidor con hcloud CLI

Y fuera de esta carpeta:

    docker-compose.cx33.yml   4 vCPU ·  8 GB ·  80 GB   → producción
    docker-compose.cx23.yml   2 vCPU ·  4 GB ·  40 GB   → PRUEBAS

## El camino corto

```bash
export HCLOUD_TOKEN=…                    # Proyecto → Security → API tokens
hcloud ssh-key create --name portatil \
    --public-key-from-file ~/.ssh/id_ed25519.pub

./infra/hetzner/crear-servidor.sh --tipo cx23
```

El script deja el servidor creado, con firewall, y con el cloud-init ya
aplicado: sin root, sin contraseñas por SSH, con ufw, swap de 2 GB, Docker y
el reloj sincronizado. Después:

```bash
ssh powergis@<IP>
cloud-init status --wait                 # → status: done

git clone <tu-repo> powergis && cd powergis
cp .env.example .env                     # y rellénalo
make check-config
make tier                                # te dice qué TIER toca
make up TIER=cx23
```

## Sin el CLI

Si prefieres la consola web: crea el servidor con Ubuntu 24.04, pega el
contenido de `cloud-init.yaml` en **Cloud config** (sustituyendo antes
`AQUI_TU_CLAVE_PUBLICA` por tu clave pública), y **desmarca IPv6**. El
firewall se crea aparte, en *Firewalls*, abriendo 22, 80 y 443.

## Las tres cosas que Hetzner hace distinto

### 1. IPv6, y por qué lo apagamos

Hetzner asigna un `/64` de IPv6 a cada servidor e invita a crear el registro
`AAAA`. Si ese registro existe, **Let's Encrypt lo prefiere** sobre el `A`
para el desafío HTTP. Docker no enruta IPv6 salvo que lo configures a mano,
así que Traefik nunca recibe ese desafío: el certificado no se emite y el
error habla de tiempos de espera sin mencionar IPv6 ni una vez.

Por eso el script crea el servidor con `--without-ipv6`: sin dirección IPv6
no hay tentación de crear el `AAAA`, y el problema no puede darse.

Si más adelante quieres IPv6 de verdad, el orden es: activarlo en
`/etc/docker/daemon.json`, comprobar que Traefik escucha en `::`, y **sólo
entonces** crear el `AAAA`.

### 2. Dos cortafuegos, no uno

El firewall de Hetzner filtra en su red, antes de llegar a la máquina. `ufw`
filtra dentro. El cloud-init configura los dos con las mismas reglas a
propósito: si alguien toca el de Hetzner por error, `ufw` sigue en pie.

Cuando algo no conecta, mira los dos. Es la causa más común de «no me
responde el 443» en Hetzner.

### 3. El drop-in de SSH

Las imágenes de Ubuntu 24.04 traen `/etc/ssh/sshd_config.d/50-cloud-init.conf`,
y los ficheros de ese directorio **ganan** sobre `sshd_config`. Editar el
principal —que es lo que dice casi toda guía— deja la contraseña activada y la
máquina parece endurecida sin estarlo.

El cloud-init escribe `99-powergis.conf`, que ordena después y tiene la última
palabra. Compruébalo:

```bash
sshd -T | grep -E 'permitrootlogin|passwordauthentication'
# permitrootlogin no
# passwordauthentication no
```

## Copias de seguridad

Hetzner tiene Object Storage compatible con S3 en las mismas regiones. En
`.env`:

```
BACKUP_S3_ENDPOINT=https://nbg1.your-objectstorage.com
BACKUP_S3_BUCKET=powergis-backups
BACKUP_S3_KEY=…
BACKUP_S3_SECRET=…
BACKUP_GPG_PASSPHRASE=…
```

Las credenciales se generan en *Security → Object Storage keys*. Pon el bucket
en la misma región que el servidor.

Los **snapshots** de Hetzner no sustituyen a esto: capturan el volumen a mitad
de una escritura, así que un `pgdata` restaurado desde snapshot puede estar
inconsistente. Sirven para volver atrás tras un cambio de sistema, no para
recuperar la base de datos.

Y como siempre: `make restore-test`. Una copia que nunca se ha restaurado no
es una copia.

## Si te quedas sin disco

El CX23 son 40 GB y el CX33 son 80. El almacén completo del INE más los
backups los llenan antes de lo que parece.

```bash
df -h /
docker system df                    # imágenes viejas ocupan mucho
docker image prune -af
```

Si el problema es `pgdata`, engánchale un Volume de Hetzner (se amplía en
caliente, cuesta céntimos por GB) y mueve el volumen de datos ahí. No subas de
servidor sólo por disco: sale más caro.

## Pasar de CX23 a CX33

No hay que rehacer el almacén, pero sí hay que sacar los datos: son servidores
distintos, no un redimensionado.

```bash
# en el CX23
make backup
scp powergis@<ip-vieja>:~/powergis/... .   # o desde el Object Storage

# en el CX33, tras make up TIER=cx33 y make migrate
gunzip -c volcado.sql.gz | docker compose exec -T postgres \
    psql -U powergis -d powergis
```

Hetzner sí permite **redimensionar** un servidor conservando el disco
(`hcloud server change-type --keep-disk`), y en ese caso los volúmenes se
conservan y basta con `make up TIER=cx33`. Es el camino recomendado si vas de
CX23 a CX33 en el mismo proyecto.
