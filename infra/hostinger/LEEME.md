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

### D · Git — la buena, cuando esto deje de ser un experimento

Repositorio **privado** en GitHub o GitLab, una clave de despliegue de solo
lectura en el VPS, y desplegar pasa a ser:

```bash
cd ~/powergis && git pull && make up
```

Ventajas reales sobre el paquete: historial de qué cambió y cuándo, vuelta
atrás inmediata si un despliegue rompe algo, y no depende de que tu portátil
tenga la última copia. La razón de no empezar por aquí es solo que añade
pasos antes de ver el sistema funcionando.

> **Lo que no debe subir nunca al repositorio:** el `.env`. Ya está en
> `.gitignore`. Los secretos viven en el VPS y en `wp-config.php`, en ningún
> otro sitio.

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
