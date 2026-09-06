/**
 * PowerGIS · render del informe.
 *
 * Un solo fichero para todo: KPIs, gráficos (ECharts), tablas avanzadas,
 * GeoLens (MapLibre) y PlaceRank. Se alimenta de UN payload JSON.
 *
 * Decisiones que importan:
 *
 * · Las secciones bloqueadas llegan con `available:false` y SIN datos. Aquí se
 *   pintan como teaser con CTA. No hay nada premium en el DOM que ocultar.
 * · El mapa une valores y geometrías con `setFeatureState`: las teselas solo
 *   llevan `geo_code`, así una misma tesela sirve a todos los usuarios y el
 *   caché del CDN es perfecto.
 * · `null` se pinta como «no disponible», nunca como 0.
 *
 * @package PowerGIS
 */

(function () {
	'use strict';

	const CFG = window.PowerGISConfig || {};
	const T = CFG.i18n || {};

	const PALETTE = ['#2563eb', '#f59e0b', '#059669', '#7c3aed', '#dc2626', '#0891b2'];
	const SEQ = ['#eff6ff', '#bfdbfe', '#60a5fa', '#2563eb', '#1e40af'];
	const SEQ_NEG = ['#fef2f2', '#fecaca', '#f87171', '#dc2626', '#991b1b'];

	// ------------------------------------------------------------------ //
	// Utilidades
	// ------------------------------------------------------------------ //

	const el = (tag, cls, text) => {
		const node = document.createElement(tag);
		if (cls) node.className = cls;
		if (text !== undefined && text !== null) node.textContent = String(text);
		return node;
	};

	const fmt = (value, type, decimals) => {
		if (value === null || value === undefined) return T.noData || 'n. d.';
		if (typeof value !== 'number') return String(value);
		const d = decimals === undefined ? 2 : decimals;
		const opts = { minimumFractionDigits: d, maximumFractionDigits: d };
		switch (type) {
			case 'int':
				return value.toLocaleString('es-ES', { maximumFractionDigits: 0 });
			case 'pct':
				return value.toLocaleString('es-ES', opts) + ' %';
			case 'eur':
				return value.toLocaleString('es-ES', { maximumFractionDigits: 0 }) + ' €';
			default:
				return value.toLocaleString('es-ES', opts);
		}
	};

	const api = async (path, options) => {
		const response = await fetch(CFG.restUrl + path, Object.assign({
			headers: { 'X-WP-Nonce': CFG.nonce, 'Content-Type': 'application/json' },
			credentials: 'same-origin',
		}, options || {}));
		if (!response.ok) {
			const body = await response.json().catch(() => ({}));
			const error = new Error(body.message || response.statusText);
			error.status = response.status;
			error.code = body.code;
			throw error;
		}
		return response.json();
	};

	// ------------------------------------------------------------------ //
	// KPIs
	// ------------------------------------------------------------------ //

	function renderKpis(container, kpis) {
		if (!kpis || !kpis.length) return;
		const row = el('div', 'pg-kpis');
		kpis.forEach((kpi) => {
			const card = el('div', 'pg-kpi' + (kpi.missing ? ' pg-kpi--missing' : ''));
			card.appendChild(el('div', 'pg-kpi__label', kpi.label));

			const value = el('div', 'pg-kpi__value');
			if (kpi.missing) {
				value.textContent = kpi.note || T.noData;
				value.title = kpi.note || '';
			} else {
				value.textContent = fmt(kpi.value, unitType(kpi.unit), kpi.decimals);
				const unit = el('span', 'pg-kpi__unit', kpi.unit === '%' ? '' : kpi.unit);
				value.appendChild(unit);
			}
			card.appendChild(value);

			if (kpi.percentile !== null && kpi.percentile !== undefined) {
				card.appendChild(el(
					'div', 'pg-kpi__pct',
					'Percentil ' + fmt(kpi.percentile, 'float', 0) + ' del ámbito'
				));
			}
			row.appendChild(card);
		});
		container.appendChild(row);
	}

	const unitType = (unit) => {
		if (unit === '%') return 'pct';
		if (unit === 'EUR') return 'eur';
		if (unit === 'personas' || unit === 'ud' || unit === 'días') return 'int';
		return 'float';
	};

	// ------------------------------------------------------------------ //
	// Gráficos (ECharts)
	// ------------------------------------------------------------------ //

	const charts = [];

	function renderChart(container, chart) {
		if (!window.echarts) return;
		const wrapper = el('div', 'pg-chart');
		wrapper.style.height = '340px';
		container.appendChild(wrapper);

		const instance = window.echarts.init(wrapper, null, { renderer: 'canvas' });
		instance.setOption(chartOption(chart));
		charts.push(instance);
	}

	function chartOption(chart) {
		const type = chart.type.startsWith('bar') ? 'bar' : (chart.type === 'area' ? 'line' : chart.type);
		return {
			color: PALETTE,
			title: { text: chart.title, left: 0, textStyle: { fontSize: 14, fontWeight: 600 } },
			grid: { left: 56, right: 16, top: 56, bottom: 72, containLabel: true },
			tooltip: {
				trigger: 'axis',
				valueFormatter: (v) => fmt(v, unitType(chart.unit), 2),
			},
			legend: { bottom: 0, type: 'scroll' },
			xAxis: {
				type: 'category',
				data: chart.x,
				axisLabel: { rotate: chart.x.length > 8 ? 35 : 0, hideOverlap: true },
			},
			yAxis: { type: 'value', axisLabel: { formatter: (v) => fmt(v, 'int', 0) } },
			series: chart.series.map((serie) => ({
				name: serie.name,
				type: type,
				stack: chart.stack ? 'total' : undefined,
				areaStyle: chart.type === 'area' ? {} : undefined,
				smooth: type === 'line',
				// `connectNulls: false` es deliberado: un hueco se ve como hueco.
				connectNulls: false,
				data: serie.data,
			})),
		};
	}

	// ------------------------------------------------------------------ //
	// Tablas avanzadas
	// ------------------------------------------------------------------ //

	function renderTable(container, table) {
		const box = el('div', 'pg-table');
		box.appendChild(el('h4', 'pg-table__title', table.title));

		const controls = el('div', 'pg-table__controls');
		const search = el('input', 'pg-table__search');
		search.type = 'search';
		search.placeholder = 'Filtrar zonas…';
		controls.appendChild(search);
		box.appendChild(controls);

		const scroll = el('div', 'pg-table__scroll');
		const element = el('table');
		const thead = el('thead');
		const headRow = el('tr');

		let sortKey = null;
		let sortAsc = false;

		table.columns.forEach((column) => {
			const th = el('th', column.type === 'text' ? '' : 'pg-num', column.label);
			th.tabIndex = 0;
			th.setAttribute('role', 'button');
			const sort = () => {
				sortAsc = sortKey === column.key ? !sortAsc : false;
				sortKey = column.key;
				draw();
			};
			th.addEventListener('click', sort);
			th.addEventListener('keydown', (event) => {
				if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); }
			});
			headRow.appendChild(th);
		});
		thead.appendChild(headRow);
		element.appendChild(thead);

		const tbody = el('tbody');
		element.appendChild(tbody);
		scroll.appendChild(element);
		box.appendChild(scroll);

		if (table.footnote) {
			box.appendChild(el('p', 'pg-table__note', table.footnote));
		}

		const tops = new Set(table.highlights && table.highlights.top || []);
		const bottoms = new Set(table.highlights && table.highlights.bottom || []);

		function draw() {
			const needle = search.value.trim().toLowerCase();
			let rows = table.rows.filter((row) =>
				!needle || String(row.zona || '').toLowerCase().includes(needle)
			);

			if (sortKey) {
				rows = rows.slice().sort((a, b) => {
					const x = a[sortKey];
					const y = b[sortKey];
					// Los huecos siempre al final, ordenes como ordenes.
					if (x === null || x === undefined) return 1;
					if (y === null || y === undefined) return -1;
					if (typeof x === 'number' && typeof y === 'number') return sortAsc ? x - y : y - x;
					return sortAsc ? String(x).localeCompare(String(y), 'es')
						: String(y).localeCompare(String(x), 'es');
				});
			}

			tbody.innerHTML = '';
			rows.forEach((row) => {
				const tr = el('tr');
				if (tops.has(row.geo_code)) tr.className = 'pg-row--top';
				else if (bottoms.has(row.geo_code)) tr.className = 'pg-row--bottom';

				table.columns.forEach((column) => {
					const value = row[column.key];
					const td = el('td', column.type === 'text' ? '' : 'pg-num');
					if (value === null || value === undefined) {
						td.className += ' pg-na';
						td.textContent = T.noData;
						td.title = T.secreto || '';
					} else {
						td.textContent = fmt(value, column.type, column.decimals);
					}
					tr.appendChild(td);
				});
				tbody.appendChild(tr);
			});
		}

		search.addEventListener('input', draw);
		draw();
		container.appendChild(box);
	}

	// ------------------------------------------------------------------ //
	// GeoLens
	// ------------------------------------------------------------------ //

	function renderGeoLens(container, geolens) {
		if (!geolens || !geolens.layers || !geolens.layers.length) return;

		const section = el('section', 'pg-geolens');
		section.id = 'geolens';
		section.appendChild(el('h2', null, 'GeoLens'));

		const layout = el('div', 'pg-geolens__layout');
		const panel = el('div', 'pg-geolens__panel');
		const mapBox = el('div', 'pg-geolens__map');
		mapBox.style.height = '520px';
		layout.appendChild(panel);
		layout.appendChild(mapBox);
		section.appendChild(layout);
		container.appendChild(section);

		if (!window.maplibregl) {
			mapBox.appendChild(el('p', 'pg-notice', 'El mapa no está disponible en este navegador.'));
			renderLayerTable(mapBox, geolens.layers[0]);
			return;
		}

		const map = new window.maplibregl.Map({
			container: mapBox,
			style: { version: 8, sources: {}, layers: [], glyphs: CFG.tilesUrl + 'glyphs/{fontstack}/{range}.pbf' },
			center: geolens.center || [-3.7, 40.4],
			zoom: 5,
			attributionControl: true,
		});
		map.addControl(new window.maplibregl.NavigationControl(), 'top-right');

		let active = null;
		let degraded = false;

		// Sin teselas generadas todavía, el mapa no puede pintar geometrías.
		// Los DATOS sí existen: se muestran como tabla en vez de dejar un hueco
		// gris y un error en consola.
		map.on('error', function (event) {
			if (degraded) return;
			degraded = true;
			console.warn('[powergis] GeoLens sin teselas:', event && event.error);
			mapBox.innerHTML = '';
			const notice = el('div', 'pg-notice');
			notice.innerHTML = '<strong>Mapa no disponible.</strong> Faltan las teselas ' +
				'vectoriales (<code>infra/build-tiles.sh</code>). Los datos de las capas ' +
				'sí están calculados y se muestran aquí debajo.';
			mapBox.appendChild(notice);
			renderLayerTable(mapBox, active || geolens.layers[0]);
		});

		map.on('load', () => {
			map.addSource('zonas', {
				type: 'vector',
				url: CFG.tilesUrl + geolens.tiles.url.replace('pmtiles://', ''),
				promoteId: geolens.tiles.promote_id,
				attribution: geolens.attribution,
			});
			map.addLayer({
				id: 'zonas-fill',
				type: 'fill',
				source: 'zonas',
				'source-layer': geolens.tiles.source_layer,
				paint: {
					'fill-color': ['coalesce', ['feature-state', 'color'], '#e2e8f0'],
					'fill-opacity': 0.78,
				},
			});
			map.addLayer({
				id: 'zonas-line',
				type: 'line',
				source: 'zonas',
				'source-layer': geolens.tiles.source_layer,
				paint: { 'line-color': '#94a3b8', 'line-width': 0.5 },
			});

			const initial = geolens.layers.find((l) => l.default_on) || geolens.layers[0];
			activate(initial);
		});

		function colorFor(layer, value) {
			if (value === null || value === undefined) return '#e2e8f0';
			const ramp = layer.palette === 'sequential-negative' ? SEQ_NEG : SEQ;
			const breaks = layer.breaks || [];
			for (let i = 1; i < breaks.length; i += 1) {
				if (value <= breaks[i]) return ramp[Math.min(i - 1, ramp.length - 1)];
			}
			return ramp[ramp.length - 1];
		}

		function activate(layer) {
			if (!layer) return;
			active = layer;
			if (degraded) {
				const old = mapBox.querySelector('.pg-layer-table');
				if (old) old.remove();
				renderLayerTable(mapBox, layer);
				renderLegend(layer);
				panel.querySelectorAll('.pg-switch').forEach(function (node) {
					node.classList.toggle('is-active', node.dataset.layer === layer.id);
				});
				return;
			}
			// Sin recargar teselas: solo cambia el estado de cada feature.
			Object.keys(layer.values).forEach((code) => {
				map.setFeatureState(
					{ source: 'zonas', sourceLayer: geolens.tiles.source_layer, id: code },
					{ color: colorFor(layer, layer.values[code]) }
				);
			});
			renderLegend(layer);
			panel.querySelectorAll('.pg-switch').forEach((node) => {
				node.classList.toggle('is-active', node.dataset.layer === layer.id);
			});
		}

		const legend = el('div', 'pg-geolens__legend');

		function renderLegend(layer) {
			legend.innerHTML = '';
			legend.appendChild(el('div', 'pg-legend__title', layer.label));
			const ramp = layer.palette === 'sequential-negative' ? SEQ_NEG : SEQ;
			(layer.breaks || []).slice(0, -1).forEach((value, index) => {
				const item = el('div', 'pg-legend__item');
				const swatch = el('span', 'pg-legend__swatch');
				swatch.style.background = ramp[Math.min(index, ramp.length - 1)];
				item.appendChild(swatch);
				item.appendChild(el('span', null,
					fmt(value, unitType(layer.unit), 1) + ' – ' + fmt(layer.breaks[index + 1], unitType(layer.unit), 1)));
				legend.appendChild(item);
			});
			const na = el('div', 'pg-legend__item');
			const naSwatch = el('span', 'pg-legend__swatch');
			naSwatch.style.background = '#e2e8f0';
			na.appendChild(naSwatch);
			na.appendChild(el('span', null, T.noData));
			legend.appendChild(na);
		}

		// Panel de switches, agrupado por sección.
		Object.keys(geolens.groups || {}).forEach((group) => {
			panel.appendChild(el('h4', 'pg-geolens__group', group));
			geolens.groups[group].forEach((id) => {
				const layer = geolens.layers.find((l) => l.id === id);
				if (!layer) return;
				const button = el('button', 'pg-switch', layer.label);
				button.type = 'button';
				button.dataset.layer = layer.id;
				button.addEventListener('click', () => activate(layer));
				panel.appendChild(button);
			});
		});
		panel.appendChild(legend);

		map.on('mousemove', 'zonas-fill', (event) => {
			map.getCanvas().style.cursor = 'pointer';
			const feature = event.features && event.features[0];
			if (!feature || !active) return;
			const code = feature.id;
			const value = active.values[code];
			showTooltip(mapBox, event.point, active.label + ': ' + fmt(value, unitType(active.unit), 1));
		});
		map.on('mouseleave', 'zonas-fill', () => {
			map.getCanvas().style.cursor = '';
			hideTooltip(mapBox);
		});
	}

	/**
	 * Respaldo de GeoLens sin mapa: los valores de la capa, ordenados.
	 * Un hueco gris no informa de nada; esta tabla sí.
	 */
	function renderLayerTable(container, layer) {
		if (!layer) return;
		const box = el('div', 'pg-layer-table');
		box.appendChild(el('h4', null, layer.label));

		const rows = Object.keys(layer.values)
			.map(function (code) { return { code: code, value: layer.values[code] }; })
			.sort(function (a, b) {
				if (a.value === null) return 1;
				if (b.value === null) return -1;
				return b.value - a.value;
			});

		const table = el('table');
		const tbody = el('tbody');
		rows.forEach(function (row) {
			const tr = el('tr');
			tr.appendChild(el('td', null, row.code));
			const td = el('td', 'pg-num');
			if (row.value === null) {
				td.className += ' pg-na';
				td.textContent = T.noData;
			} else {
				td.textContent = fmt(row.value, unitType(layer.unit), 1);
			}
			tr.appendChild(td);
			tbody.appendChild(tr);
		});
		table.appendChild(tbody);
		box.appendChild(table);
		container.appendChild(box);
	}

	function showTooltip(container, point, text) {
		let tip = container.querySelector('.pg-map-tip');
		if (!tip) {
			tip = el('div', 'pg-map-tip');
			container.appendChild(tip);
		}
		tip.textContent = text;
		tip.style.left = point.x + 12 + 'px';
		tip.style.top = point.y + 12 + 'px';
		tip.style.display = 'block';
	}

	function hideTooltip(container) {
		const tip = container.querySelector('.pg-map-tip');
		if (tip) tip.style.display = 'none';
	}

	// ------------------------------------------------------------------ //
	// PlaceRank
	// ------------------------------------------------------------------ //

	function renderPlaceRank(container, placerank, postId) {
		if (!placerank || !placerank.rows || !placerank.rows.length) return;

		const section = el('section', 'pg-placerank');
		section.id = 'placerank';
		section.appendChild(el('h2', null, 'PlaceRank'));
		section.appendChild(el('p', 'pg-muted', placerank.method));

		// Ajuste de pesos en vivo: el backend reutiliza las dimensiones ya
		// calculadas, así que responde al instante.
		const sliders = el('div', 'pg-weights');
		const weights = Object.assign({}, placerank.weights);
		const table = el('div');

		Object.keys(weights).forEach((key) => {
			const row = el('label', 'pg-weight');
			row.appendChild(el('span', 'pg-weight__label', key));
			const input = el('input');
			input.type = 'range';
			input.min = '0';
			input.max = '100';
			input.value = String(Math.round(weights[key] * 100));
			const out = el('span', 'pg-weight__value', input.value + ' %');
			input.addEventListener('input', () => { out.textContent = input.value + ' %'; });
			input.addEventListener('change', async () => {
				const payload = {};
				sliders.querySelectorAll('input[type=range]').forEach((node) => {
					payload[node.dataset.key] = Number(node.value) / 100;
				});
				try {
					const updated = await api('/projects/' + postId + '/placerank', {
						method: 'POST', body: JSON.stringify(payload),
					});
					drawRank(table, updated.rows);
				} catch (error) {
					console.warn('[powergis] no se pudo recalcular el PlaceRank', error);
				}
			});
			input.dataset.key = key;
			row.appendChild(input);
			row.appendChild(out);
			sliders.appendChild(row);
		});

		section.appendChild(sliders);
		section.appendChild(table);
		drawRank(table, placerank.rows);
		container.appendChild(section);
	}

	function drawRank(container, rows) {
		container.innerHTML = '';
		const element = el('table', 'pg-rank');
		const thead = el('thead');
		const head = el('tr');
		['#', 'Zona', 'Score', 'Categoría', 'Económico', 'Demográfico', 'Ambiental', 'Match']
			.forEach((label) => head.appendChild(el('th', null, label)));
		thead.appendChild(head);
		element.appendChild(thead);

		const tbody = el('tbody');
		rows.forEach((row) => {
			const tr = el('tr');
			tr.appendChild(el('td', 'pg-num', row.rank));
			tr.appendChild(el('td', null, row.geo_name));
			tr.appendChild(el('td', 'pg-num pg-strong', fmt(row.score, 'float', 1)));
			tr.appendChild(el('td', null, row.category));
			['economico', 'demografico', 'ambiental', 'match'].forEach((key) => {
				tr.appendChild(el('td', 'pg-num', fmt((row.dimensions || {})[key], 'float', 1)));
			});
			if (row.narrative) {
				tr.title = row.narrative;
			}
			tbody.appendChild(tr);
		});
		element.appendChild(tbody);
		container.appendChild(element);
	}

	// ------------------------------------------------------------------ //
	// Secciones bloqueadas
	// ------------------------------------------------------------------ //

	/**
	 * Marcador compacto en el sitio donde IRÍA la sección.
	 *
	 * Antes esto pintaba una caja gris con su propio botón por cada sección
	 * bloqueada: cuatro cajas idénticas seguidas, que es ruido y no convierte.
	 * Ahora sólo señala el hueco y lleva al panel único de abajo.
	 */
	function renderLockedMarker(container, section) {
		const box = el('section', 'pg-locked');
		box.id = 'seccion-' + section.id;

		const head = el('div', 'pg-locked__head');
		head.appendChild(el('h2', null, section.title));
		head.appendChild(el('span', 'pg-locked__badge', T.lockedBadge || 'Incluido en el avanzado'));
		box.appendChild(head);

		// El índice de lo que contiene: etiquetas del catálogo, sin un solo dato.
		const preview = section.preview || [];
		if (preview.length) {
			const list = el('ul', 'pg-locked__list');
			preview.forEach((label) => {
				const item = el('li');
				item.appendChild(el('span', 'pg-locked__label', label));
				// El hueco del valor se dibuja, no se rellena: el navegador
				// nunca ha recibido la cifra.
				item.appendChild(el('span', 'pg-locked__blur', '•••'));
				list.appendChild(item);
			});
			box.appendChild(list);
		}

		const link = el('a', 'pg-locked__link', T.seeUnlock || 'Ver qué incluye el informe avanzado');
		link.href = '#pg-upgrade';
		box.appendChild(link);

		container.appendChild(box);
	}

	/**
	 * Panel único de compra, al final del informe básico.
	 *
	 * Aquí es donde el cliente decide: ha leído su demografía completa, ha
	 * visto los huecos, y ahora tiene delante la lista de todo lo que le
	 * falta y un solo botón.
	 */
	function renderUpgradePanel(container, locked, postId) {
		if (!locked.length) return;

		const box = el('section', 'pg-upgrade');
		box.id = 'pg-upgrade';
		box.appendChild(el('h2', null, T.upgradeTitle || 'Completa tu informe'));
		box.appendChild(el('p', 'pg-upgrade__lead', T.upgradeLead
			|| 'Ya tienes la demografía completa de tu zona. El informe avanzado añade:'));

		const grid = el('div', 'pg-upgrade__grid');
		locked.forEach((section) => {
			const card = el('div', 'pg-upgrade__card');
			card.appendChild(el('h3', null, section.title));
			const list = el('ul');
			(section.preview || []).forEach((label) => list.appendChild(el('li', null, label)));
			card.appendChild(list);
			grid.appendChild(card);
		});
		box.appendChild(grid);

		const extras = el('ul', 'pg-upgrade__extras');
		[
			T.extraPlaceRank || 'PlaceRank: ranking ponderado de las zonas de tu ámbito',
			T.extraGeoLens || 'GeoLens: mapa por capas con todos los indicadores',
			T.extraExports || 'Descarga en Excel, PDF y PowerPoint',
		].forEach((text) => extras.appendChild(el('li', null, text)));
		box.appendChild(extras);

		const cta = el('button', 'pg-cta pg-cta--lg', T.unlock || 'Desbloquear informe avanzado');
		cta.type = 'button';

		const error = el('p', 'pg-upgrade__error');
		error.hidden = true;

		cta.addEventListener('click', async () => {
			cta.disabled = true;
			error.hidden = true;
			cta.textContent = T.redirecting || 'Conectando con el pago…';
			try {
				const result = await api('/checkout?id=' + postId, { method: 'POST' });
				if (result.url) {
					window.location.href = result.url;
					return;
				}
				if (result.already_advanced) {
					window.location.reload();
					return;
				}
				throw new Error(T.error || 'No se pudo iniciar el pago');
			} catch (exception) {
				// Nada de alert(): un modal del navegador bloquea la página
				// y se lleva por delante el momento de la compra.
				cta.disabled = false;
				cta.textContent = T.unlock || 'Desbloquear informe avanzado';
				error.textContent = exception.message || T.error;
				error.hidden = false;
			}
		});

		box.appendChild(cta);
		box.appendChild(error);
		container.appendChild(box);
	}

	// ------------------------------------------------------------------ //
	// Orquestación
	// ------------------------------------------------------------------ //

	function renderReport(root, payload) {
		root.innerHTML = '';

		if (payload.warnings && payload.warnings.length) {
			const box = el('div', 'pg-warnings');
			payload.warnings.forEach((warning) => box.appendChild(el('p', 'pg-warning', warning)));
			root.appendChild(box);
		}

		if (payload.executive_summary) {
			const summary = el('section', 'pg-summary');
			summary.appendChild(el('h2', null, 'Resumen ejecutivo'));
			renderKpis(summary, (payload.executive_summary.headline || []).map((item) => ({
				label: item.label, value: item.value, unit: item.unit,
				decimals: 0, missing: item.value === null,
			})));
			const narrative = payload.executive_summary.narrative;
			if (narrative && narrative.resumen) {
				summary.appendChild(el('p', null, narrative.resumen));
			}
			root.appendChild(summary);
		}

		const locked = [];

		(payload.sections || []).forEach((section) => {
			if (!section.available) {
				locked.push(section);
				renderLockedMarker(root, section);
				return;
			}
			const box = el('section', 'pg-section');
			box.id = 'seccion-' + section.id;
			box.appendChild(el('h2', null, section.title));

			(section.subsections || []).forEach((sub) => {
				box.appendChild(el('h3', null, sub.title));
				renderKpis(box, sub.kpis);
				(sub.charts || []).forEach((chart) => renderChart(box, chart));
				(sub.tables || []).forEach((table) => renderTable(box, table));
				if (sub.narrative) box.appendChild(el('p', null, sub.narrative));
			});
			root.appendChild(box);
		});

		renderGeoLens(root, payload.geolens);
		renderPlaceRank(root, payload.placerank, CFG.postId);
		renderUpgradePanel(root, locked, CFG.postId);

		if (payload.sources && payload.sources.length) {
			const box = el('section', 'pg-sources');
			box.appendChild(el('h2', null, 'Fuentes y metodología'));
			const list = el('ul');
			payload.sources.forEach((source) => {
				list.appendChild(el('li', null, source.name + ' — ' + source.attribution));
			});
			box.appendChild(list);
			root.appendChild(box);
		}

		window.addEventListener('resize', () => charts.forEach((chart) => chart.resize()));
	}

	async function boot() {
		const root = document.querySelector('[data-pg-report]');
		if (!root) return;

		const postId = Number(root.dataset.pgReport || CFG.postId);
		root.innerHTML = '<div class="pg-loading">' + (T.loading || 'Cargando…') + '</div>';

		// Vuelta de Stripe. El webhook desbloquea el informe en segundo plano,
		// así que al aterrizar aquí la v2 puede no existir todavía: el motor
		// devuelve la v1 (básica), que es un 200 perfectamente válido.
		//
		// Sin esto, el cliente que ACABA DE PAGAR ve su informe con las
		// secciones bloqueadas y el botón de comprar. Es el peor momento
		// posible para un fallo, y no lo detecta ningún reintento por error
		// porque no hay error: hay una respuesta correcta y antigua.
		const justPaid = /[?&]pg_pago=ok\b/.test(window.location.search);
		const waitUntil = Date.now() + 180000;   // 3 min: si el webhook no ha
		                                         // llegado, algo va mal de verdad

		let delay = 2000;
		const attempt = async () => {
			try {
				const payload = await api('/projects/' + postId + '/report');

				if (justPaid && payload.tier !== 'avanzado' && Date.now() < waitUntil) {
					root.innerHTML = '<div class="pg-loading">'
						+ (T.unlocking || 'Pago confirmado. Estamos ampliando tu informe…')
						+ '</div>';
					delay = Math.min(delay * 1.5, 10000);
					setTimeout(attempt, delay);
					return;
				}

				if (justPaid && payload.tier !== 'avanzado') {
					// Se agotó la espera. Se pinta lo que hay, pero se dice la
					// verdad en vez de volver a ofrecerle que pague.
					renderReport(root, payload);
					const notice = el('div', 'pg-notice pg-notice--warn', T.upgradeSlow
						|| 'Tu pago se ha registrado, pero el informe ampliado está tardando '
						 + 'más de lo normal. No hace falta que pagues otra vez: recarga en '
						 + 'unos minutos o escríbenos y lo revisamos.');
					root.prepend(notice);
					const panel = root.querySelector('#pg-upgrade');
					if (panel) panel.remove();   // no se le vuelve a cobrar
					return;
				}

				renderReport(root, payload);
			} catch (error) {
				if (error.status === 409 || error.code === 'report_not_ready') {
					root.innerHTML = '<div class="pg-loading">' + (T.generating || '') + '</div>';
					delay = Math.min(delay * 1.5, 15000);
					setTimeout(attempt, delay);
					return;
				}
				root.innerHTML = '<div class="pg-error">' + (error.message || T.error) + '</div>';
			}
		};
		attempt();
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', boot);
	} else {
		boot();
	}
})();
