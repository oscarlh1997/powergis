# El front, en local

Copia de trabajo del plugin **SaaS Studies** de powergis.es, para probar el
formulario real contra el motor local sin tocar el sitio en producción.

## Qué hay aquí y qué falta

Están los tres ficheros que cambian y que ya llevan el guardia de rutas:

    includes/shortcodes.php     [crear_proyecto_v6] · versión del equipo de datos, 18/10/2026
    includes/cpt-project.php    CPT project, con guardia
    includes/rest-projects.php  rutas saas/v1, con guardia

**Falta el resto del plugin, y no lo tengo yo: lo tienes tú.** Copia desde
`SAAS_STUDY/SAAS_studies/` de tus Descargas:

    saas-studies.php        el arranque del plugin
    uninstall.php
    includes/helpers.php
    includes/roles.php
    includes/taxonomies.php
    data/                   arbol.json, Estructura_CNAE2025.csv, paises.csv

Los `data/` pesan 1 MB y son los que alimentan los desplegables de ubicación y
actividad del formulario. `paises.csv` ya no lo usa: desde el 18/10/2026 el
formulario pregunta el «peso de población extranjera» (baja/media/alta) en vez
de la nacionalidad.

## Dónde va `shortcodes.php` en producción

Es un fichero del **plugin** SaaS Studies, no del tema: usa la constante
`SAAS_STUDIES_URL`, que sólo define el arranque del plugin. En el servidor:

    wp-content/plugins/saas-studies/includes/shortcodes.php

## Formulario del 18/10/2026: qué cambió y qué hace el motor con ello

* Ámbito: «Nacional» marcado por defecto; `tipo_estudio` se lee del radio
  marcado (`getTipoEstudio()`).
* Obligatorios: edad, renta anual y renta mensual (con «Indiferente» válido).
* NSE fuera del formulario y del motor; la renta mide la capacidad de consumo.
* `peso_poblacion_extranjera` (Baja/Media/Alta) → criterio sobre el % de
  población extranjera (menos / en la media / más).
* `datos_territoriales`: ocho interruptores `incluir`/`excluir`. El motor
  quita del informe la capa apagada (y la sección entera si se apagan todas
  las suyas). El interruptor inmobiliario arrastra las cinco capas de vivienda
  y Catastro a la vez; los cinco desplegables son informativos.
* Ya no se manda `comentarios`.

## Por qué tres ficheros míos y no los tuyos

Los de tu carpeta son de febrero: el `shortcodes.php` de ahí manda un payload
plano de cinco campos, no el anidado que envía tu web hoy. Probar con esa copia
sería probar un contrato que ya no existe. Los que hay aquí son los que me
enviaste en agosto.

## El guardia de rutas

`rest-projects.php` y el conector registran las mismas rutas
(`saas/v1/projects/create`, `/save-draft`, `/callback`). WordPress no avisa:
apila los dos manejadores y despacha el primero que coincida, así que gana el
que cargue antes. Un accidente, no una decisión.

Con el guardia, si el conector está activo este plugin se aparta de las rutas
REST y del CPT, y conserva todo lo demás: shortcode, taxonomías, roles.
Desactiva el conector y vuelve a hacerse cargo solo.

Comprueba en cualquier momento que no hay choques:

    make dev-rutas          .\pg rutas   en Windows

Ninguna ruta debe salir con más de un manejador.
