<?php
/**
 * Resuelve los NOMBRES de ubicación del formulario a códigos INE.
 *
 * POR QUÉ HACE FALTA
 * ------------------
 * `[crear_proyecto_v6]` pinta el árbol de ubicación con el nombre como valor:
 *
 *     opt.value = c.label;      // "Comunidad de Madrid", no "13"
 *
 * y el motor exige `scope.ine_code`. Sin resolver, toda creación de proyecto
 * se rechaza en el borde. Es el TODO anotado en `rest-projects.php`
 * («confirmar que el árbol de ubicación manda código INE, no solo el
 * nombre»): confirmado, no lo manda.
 *
 * POR QUÉ CONTRA EL MOTOR Y NO CONTRA `arbol.json`
 * ------------------------------------------------
 * `data/arbol.json` sí trae el código de CCAA («01») y de provincia («04»),
 * pero el de los 8.131 municipios es de UN dígito: se conservó el dígito de
 * control y se perdió el número de municipio. Madrid figura como «6», no como
 * «28079». Desde ese fichero el código municipal es irrecuperable.
 *
 * El motor tiene el padrón completo en `dim_geo`, así que además de ser la
 * única fuente capaz de resolver el municipio, garantiza que el código que
 * viaja existe en el almacén: formulario y datos no pueden discrepar.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Geo_Resolver {

	private Engine_Client $engine;

	public function __construct( ?Engine_Client $engine = null ) {
		$this->engine = $engine ?? new Engine_Client();
	}

	/**
	 * Devuelve el resolutor que espera `Form_Mapper::to_engine_payload()`.
	 *
	 * @return callable(string, array<string,string>): ?string
	 */
	public function as_callable(): callable {
		return fn( string $level, array $names ): ?string => $this->resolve( $level, $names );
	}

	/**
	 * @param array<string,string> $names ccaa / provincia / municipio, tal y
	 *                                    como los mandó el formulario.
	 */
	public function resolve( string $level, array $names ): ?string {
		if ( 'pais' === $level ) {
			return 'ES';
		}

		$wanted = trim( (string) ( $names[ $level ] ?? '' ) );
		if ( '' === $wanted ) {
			return null;
		}

		$cache_key = 'pg_geo_' . $level . '_' . md5( strtolower( $wanted . '|' . ( $names['provincia'] ?? '' ) ) );
		$cached    = get_transient( $cache_key );
		if ( is_string( $cached ) && '' !== $cached ) {
			return $cached;
		}

		$code = 'municipio' === $level
			? $this->resolve_municipio( $wanted, (string) ( $names['provincia'] ?? '' ) )
			: $this->resolve_by_search( $level, $wanted );

		if ( null !== $code ) {
			set_transient( $cache_key, $code, DAY_IN_SECONDS );
		}

		return $code;
	}

	/**
	 * CCAA y provincia: búsqueda directa por nombre. Los nombres a estos dos
	 * niveles son únicos en España, así que no hay que desambiguar.
	 */
	private function resolve_by_search( string $level, string $name ): ?string {
		$rows = $this->engine->search_geo( $name, $level );
		if ( is_wp_error( $rows ) || ! is_array( $rows ) ) {
			Plugin::log( 'error', 'Geo_Resolver: el motor no resolvió la ubicación', array(
				'level' => $level,
				'name'  => $name,
			) );
			return null;
		}
		return $this->best_match( $rows, $name );
	}

	/**
	 * Municipio: SIEMPRE dentro de su provincia.
	 *
	 * En España hay decenas de municipios homónimos —«Villanueva», «Los
	 * Santos», «Fuente…»— y resolver «Madrid» a nivel nacional puede devolver
	 * el municipio equivocado sin dar ningún error. El informe saldría de otra
	 * zona, con datos perfectamente válidos y perfectamente ajenos.
	 */
	private function resolve_municipio( string $name, string $provincia ): ?string {
		if ( '' === $provincia ) {
			// Sin provincia no se puede desambiguar. Antes que arriesgarse a
			// devolver el municipio de otro sitio, se falla.
			Plugin::log( 'error', 'Geo_Resolver: municipio sin provincia, no se puede desambiguar', array(
				'name' => $name,
			) );
			return null;
		}

		$provincia_code = $this->resolve_by_search( 'provincia', $provincia );
		if ( null === $provincia_code ) {
			return null;
		}

		$rows = $this->engine->children( 'provincia', $provincia_code, 'municipio' );
		if ( is_wp_error( $rows ) || ! is_array( $rows ) ) {
			return null;
		}

		return $this->best_match( $rows, $name );
	}

	/**
	 * Elige la fila cuyo nombre coincide.
	 *
	 * Primero exacto; si no, sin acentos ni mayúsculas; y sólo entonces por
	 * prefijo, que cubre los nombres bilingües del INE («Alicante/Alacant»,
	 * «Castellón/Castelló»). Nunca por «contiene»: «Madrid» aparece dentro de
	 * varios topónimos y eso es justo lo que no se quiere.
	 *
	 * @param array<int,array<string,mixed>> $rows
	 */
	private function best_match( array $rows, string $wanted ): ?string {
		$target = $this->fold( $wanted );

		foreach ( $rows as $row ) {
			if ( isset( $row['name'], $row['ine_code'] ) && (string) $row['name'] === $wanted ) {
				return (string) $row['ine_code'];
			}
		}

		foreach ( $rows as $row ) {
			if ( isset( $row['name'], $row['ine_code'] ) && $this->fold( (string) $row['name'] ) === $target ) {
				return (string) $row['ine_code'];
			}
		}

		foreach ( $rows as $row ) {
			if ( ! isset( $row['name'], $row['ine_code'] ) ) {
				continue;
			}
			$candidate = $this->fold( (string) $row['name'] );
			// «alicante/alacant» empieza por «alicante»; también al revés,
			// por si el formulario guardó la variante en el otro idioma.
			if ( str_starts_with( $candidate, $target . '/' ) || str_contains( '/' . $candidate, '/' . $target ) ) {
				return (string) $row['ine_code'];
			}
		}

		return null;
	}

	private function fold( string $text ): string {
		return strtr(
			strtolower( trim( $text ) ),
			array( 'á' => 'a', 'é' => 'e', 'í' => 'i', 'ó' => 'o', 'ú' => 'u', 'ü' => 'u', 'ñ' => 'n' )
		);
	}
}
