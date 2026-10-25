/**
 * PowerGIS · render del informe.
 *
 * Un solo fichero para todo: tarjetas, gráficos y mapa (ECharts), «Datos
 * avanzados», PlaceRank y compra. Se alimenta de UN payload JSON del motor.
 *
 * Decisiones que importan (especificación de visualización v2, 20/10/2026):
 *
 * · Todo dato se enseña con su etiqueta: «Dato de su provincia o comunidad»,
 *   «En actualización», «Dato antiguo», «Estimado» (`kpi.flags`, `row._flags`).
 *   Nunca «dudoso».
 * · El color de valoración compara con P25/P75 de las zonas del informe; con
 *   menos de 5 zonas, con el total nacional (`reference`). El color nunca va
 *   solo: siempre icono + texto.
 * · Colores y tipografías salen de variables CSS (`--pg-*`, report.css): la
 *   marca se cambia ahí, no aquí.
 * · Las secciones bloqueadas llegan con `available:false` y SIN datos.
 * · `null` se pinta como «Sin dato», nunca como 0.
 * · Nada depende de Graphina ni de Elementor.
 *
 * @package PowerGIS
 */

(function () {
	'use strict';

	const CFG = window.PowerGISConfig || {};
	const T = CFG.i18n || {};
	// Enlace compartido: el invitado ve el informe y nada más. Sin compra,
	// sin exportaciones y sin reajuste del PlaceRank (son del dueño).
	const SHARED = Boolean(CFG.shareToken);

	// ------------------------------------------------------------------ //
	// Marca: todo color sale de las variables CSS de report.css
	// ------------------------------------------------------------------ //

	let TOKENS = null;
	function tok() {
		if (TOKENS) return TOKENS;
		const root = document.querySelector('.pg-report') || document.documentElement;
		const st = getComputedStyle(root);
		const v = (name, fallback) => (st.getPropertyValue(name) || '').trim() || fallback;
		TOKENS = {
			ink: v('--pg-ink', '#121D27'),
			muted: v('--pg-muted', '#56616d'),
			line: v('--pg-line', '#dde3ea'),
			brand: v('--pg-brand', '#1B5A82'),
			font: v('--pg-font-body', 'system-ui, sans-serif'),
			fav: v('--pg-fav', '#1f6fb2'),
			mid: v('--pg-mid', '#8a8984'),
			unfav: v('--pg-unfav', '#d0631f'),
			nodata: v('--pg-nodata', '#e6e8eb'),
			seq: [1, 2, 3, 4, 5].map((i) => v('--pg-seq-' + i, ['#c6dbef', '#86b6ef', '#4f8fdb', '#1c5cab', '#0d366b'][i - 1])),
			div: [1, 2, 3, 4, 5].map((i) => v('--pg-div-' + i, ['#ca0020', '#f4a582', '#f7f7f7', '#92c5de', '#0571b0'][i - 1])),
			cat: [1, 2, 3, 4, 5, 6].map((i) => v('--pg-cat-' + i, ['#1B5A82', '#d0631f', '#7aa6c8', '#A3307E', '#8a8984', '#3c8d5a'][i - 1])),
		};
		return TOKENS;
	}

	// ------------------------------------------------------------------ //
	// Utilidades
	// ------------------------------------------------------------------ //

	const el = (tag, cls, text) => {
		const node = document.createElement(tag);
		if (cls) node.className = cls;
		if (text !== undefined && text !== null) node.textContent = String(text);
		return node;
	};

	const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

	const fmt = (value, type, decimals) => {
		if (value === null || value === undefined) return T.noData || 'Sin dato';
		if (typeof value !== 'number') return String(value);
		const d = decimals === undefined ? 2 : decimals;
		const opts = { minimumFractionDigits: d, maximumFractionDigits: d };
		switch (type) {
			case 'int':
				return value.toLocaleString('es-ES', { maximumFractionDigits: 0 });
			case 'pct':
				return value.toLocaleString('es-ES', opts) + ' %';
			case 'eur':
				// Rentas y precios por hogar sin decimales; el alquiler por m²
				// (11,40 €) los necesita. Manda el `decimals` del indicador.
				return value.toLocaleString('es-ES', {
					minimumFractionDigits: decimals ? d : 0,
					maximumFractionDigits: decimals ? d : 0,
				}) + ' €';
			default:
				return value.toLocaleString('es-ES', opts);
		}
	};

	const unitType = (unit) => {
		if (unit === '%') return 'pct';
		if (unit === 'EUR') return 'eur';
		if (unit === 'personas' || unit === 'ud' || unit === 'días' || unit === 'h') return 'int';
		return 'float';
	};

	/** Valor con su unidad, como lo lee una persona: «2.652 h», «8,4 ‰». */
	const fmtUnit = (value, unit, decimals) => {
		const type = unitType(unit);
		const text = fmt(value, type, decimals);
		if (!isNum(value) || type === 'pct' || type === 'eur' || !unit
			|| unit === 'indice' || unit === 'ratio' || unit === 'ud') return text;
		return text + ' ' + unit;
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
	// Iconos (trazos tipo Lucide, en línea: sin peticiones extra)
	// ------------------------------------------------------------------ //

	const ICONS = {
		check: '<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
		minus: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
		alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
		slash: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
		hourglass: '<path d="M5 22h14M5 2h14M17 22v-4.2a2 2 0 0 0-.6-1.4L12 12l-4.4 4.4a2 2 0 0 0-.6 1.4V22M7 2v4.2a2 2 0 0 0 .6 1.4L12 12l4.4-4.4a2 2 0 0 0 .6-1.4V2"/>',
		up: '<path d="M14 9 9 4 4 9"/><path d="M20 20h-7a4 4 0 0 1-4-4V4"/>',
		clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
		calc: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01M8 10h.01M12 10h.01M16 10h.01"/>',
		lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
		download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
	};

	function icon(name) {
		const span = el('span', 'pg-icon');
		span.setAttribute('aria-hidden', 'true');
		span.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
			+ 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
		return span;
	}

	// ------------------------------------------------------------------ //
	// Valoración (color + icono + texto) y marcas del dato
	// ------------------------------------------------------------------ //

	const RATING = {
		favorable: { icon: 'check', text: 'Favorable' },
		media: { icon: 'minus', text: 'En la media' },
		desfavorable: { icon: 'alert', text: 'Desfavorable' },
	};

	const FLAGS = {
		heredado: { icon: 'up', text: 'Dato de su provincia o comunidad',
			tip: 'La fuente no publica este dato para la zona: lleva el valor de su provincia o comunidad. No se compara entre zonas.' },
		heredado_municipio: { icon: 'up', text: 'Dato de su municipio',
			tip: 'La fuente no publica este dato por distrito ni por sección censal: la zona lleva el valor de su municipio. No se compara entre zonas.' },
		provisional: { icon: 'hourglass', text: 'En actualización',
			tip: 'La fuente oficial está pendiente de verificar o de publicarse con este detalle. Puede cambiar en la próxima actualización.' },
		antiguo: { icon: 'clock', text: 'Dato antiguo',
			tip: 'Es el último dato publicado, pero tiene más de cuatro años.' },
		estimado: { icon: 'calc', text: 'Estimado',
			tip: 'Lo calcula PowerGIS con un modelo a partir de datos oficiales: no es una cifra publicada.' },
	};

	/** Misma regla que el motor (`domain.estado.clase`). */
	function rate(value, ref, direction) {
		if (!isNum(value) || !ref || !direction) return null;
		const alto = value >= ref.p75;
		const bajo = value <= ref.p25;
		if (alto === bajo) return 'media';
		return (direction > 0 ? alto : bajo) ? 'favorable' : 'desfavorable';
	}

	const ratingColor = (rating) => (rating ? tok()[{ favorable: 'fav', media: 'mid', desfavorable: 'unfav' }[rating]] : tok().brand);

	function refText(ref) {
		if (!ref) return '';
		if (ref.base === 'nacional') {
			return 'Comparado con el total nacional (' + fmt(ref.valor, 'float', 1) + ', ±5 %)';
		}
		return 'Comparado con las ' + fmt(ref.n, 'int') + ' zonas del informe (P25 ' + fmt(ref.p25, 'float', 1)
			+ ' · P75 ' + fmt(ref.p75, 'float', 1) + ')';
	}

	function ratingChip(rating, ref) {
		const r = RATING[rating];
		if (!r) return null;
		const chip = el('span', 'pg-rating pg-rating--' + rating);
		chip.appendChild(icon(r.icon));
		chip.appendChild(el('span', null, r.text));
		if (ref) chip.title = refText(ref);
		return chip;
	}

	function flagChips(flags) {
		const box = el('span', 'pg-flags');
		(flags || []).forEach((flag) => {
			const f = FLAGS[flag];
			if (!f) return;
			const chip = el('span', 'pg-flag pg-flag--' + flag);
			chip.appendChild(icon(f.icon));
			chip.appendChild(el('span', null, f.text));
			chip.title = f.tip;
			box.appendChild(chip);
		});
		return box.children.length ? box : null;
	}

	// ------------------------------------------------------------------ //
	// Textos genéricos (plantillas con marcadores, es-ES)
	// ------------------------------------------------------------------ //

	const FRASE = {
		favorable: 'un valor favorable',
		media: 'un valor en la franja media',
		desfavorable: 'un valor desfavorable',
	};

	function baseText(ref) {
		if (!ref) return '';
		return ref.base === 'nacional' ? 'el total nacional' : 'las ' + fmt(ref.n, 'int') + ' zonas comparadas';
	}

	/** «{indicador} en {ámbito}: {valor}, {valoración} frente a {base}.» */
	function kpiSentence(kpi, ambito) {
		let text = kpi.label + ' en ' + ambito + ': ' + fmtUnit(kpi.value, kpi.unit, kpi.decimals);
		if (kpi.rating && kpi.reference) text += ', ' + FRASE[kpi.rating] + ' frente a ' + baseText(kpi.reference);
		return text + '.';
	}

	function subsectionText(sub, ctx) {
		const parts = [];
		const kpis = (sub.kpis || []).filter((k) => !k.missing);
		const rated = kpis.filter((k) => k.rating);
		(rated.length ? rated : kpis).slice(0, 2).forEach((k) => parts.push(kpiSentence(k, ctx.ambito)));
		const table = (sub.tables || [])[0];
		const top = table && table.highlights && table.highlights.top || [];
		if (top.length) {
			const names = top.map((code) => (table.rows.find((r) => r.geo_code === code) || {}).zona).filter(Boolean);
			if (names.length) parts.push('Destacan ' + listText(names) + '.');
		}
		const flags = new Set(kpis.flatMap((k) => k.flags || []));
		if (flags.has('estimado')) parts.push('Algunas cifras son estimaciones de PowerGIS y lo indican con la etiqueta «Estimado».');
		if (flags.has('heredado')) parts.push('Los datos que la fuente sólo publica por provincia o comunidad llevan su etiqueta y no se comparan entre zonas.');
		if (flags.has('heredado_municipio')) parts.push('Los datos que la fuente sólo publica por municipio llevan la etiqueta «Dato de su municipio» y no se comparan entre zonas.');
		return parts.join(' ');
	}

	const listText = (items) => (items.length < 2 ? items.join('')
		: items.slice(0, -1).join(', ') + ' y ' + items[items.length - 1]);

	function chartSentence(title, items, unit, decimals) {
		const withData = items.filter((i) => isNum(i.value));
		if (!withData.length) return title + '.';
		const max = withData.reduce((a, b) => (b.value > a.value ? b : a));
		const min = withData.reduce((a, b) => (b.value < a.value ? b : a));
		if (max === min) return title + ': ' + max.name + ', ' + fmtUnit(max.value, unit, decimals) + '.';
		return title + '. Valor más alto: ' + max.name + ' (' + fmtUnit(max.value, unit, decimals) + '); más bajo: '
			+ min.name + ' (' + fmtUnit(min.value, unit, decimals) + ').';
	}

	// ------------------------------------------------------------------ //
	// Tarjetas (KPI)
	// ------------------------------------------------------------------ //

	function renderKpis(container, kpis) {
		if (!kpis || !kpis.length) return;
		const row = el('div', 'pg-kpis');
		kpis.forEach((kpi) => {
			const card = el('div', 'pg-kpi' + (kpi.missing ? ' pg-kpi--missing' : '')
				+ (kpi.rating ? ' pg-kpi--' + kpi.rating : ''));
			card.appendChild(el('div', 'pg-kpi__label', kpi.label));

			const value = el('div', 'pg-kpi__value');
			if (kpi.missing) {
				value.appendChild(icon('slash'));
				value.appendChild(el('span', null, 'Sin dato'));
				card.appendChild(value);
				if (kpi.note) card.appendChild(el('div', 'pg-kpi__ref', kpi.note));
			} else {
				value.textContent = fmt(kpi.value, unitType(kpi.unit), kpi.decimals);
				const unit = unitType(kpi.unit);
				if (unit !== 'pct' && unit !== 'eur' && kpi.unit && kpi.unit !== 'indice' && kpi.unit !== 'ratio') {
					value.appendChild(el('span', 'pg-kpi__unit', kpi.unit));
				}
				card.appendChild(value);
				const meta = el('div', 'pg-kpi__meta');
				const chip = ratingChip(kpi.rating, kpi.reference);
				if (chip) meta.appendChild(chip);
				const flags = flagChips(kpi.flags);
				if (flags) meta.appendChild(flags);
				if (meta.children.length) card.appendChild(meta);
				const ref = [];
				if (kpi.rating && kpi.reference) ref.push(refText(kpi.reference));
				if (kpi.period) ref.push('Dato de ' + kpi.period.slice(0, 4));
				if (ref.length) card.appendChild(el('div', 'pg-kpi__ref', ref.join(' · ')));
			}
			row.appendChild(card);
		});
		container.appendChild(row);
	}

	// ------------------------------------------------------------------ //
	// Gráficos (ECharts, inicio perezoso: se dibujan al llegar a pantalla)
	// ------------------------------------------------------------------ //

	const charts = [];
	const pending = new Map();
	let observer = null;

	// ECharts (≈ 330 kB) se pide DESPUÉS de pintar el informe: así no compite
	// con el JSON y textos, tarjetas y tablas salen antes; los gráficos se
	// dibujan en cuanto llega. Si la página ya lo trae, se usa ese.
	let echartsLoaded = null;
	const echartsReady = new Promise((resolve) => { echartsLoaded = resolve; });
	function loadEcharts() {
		if (window.echarts) { echartsLoaded(); return; }
		if (document.querySelector('script[data-pg-echarts]')) return;
		const script = document.createElement('script');
		script.src = CFG.echartsUrl || 'https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js';
		script.async = true;
		script.dataset.pgEcharts = '';
		script.addEventListener('load', echartsLoaded);
		script.addEventListener('error', () => { console.warn('[powergis] no se pudo cargar ECharts'); echartsLoaded(); });
		document.head.appendChild(script);
	}
	echartsReady.then(() => {
		if (!observer) { Array.from(pending.keys()).forEach(drawPending); return; }
		pending.forEach((_, wrapper) => { observer.unobserve(wrapper); observer.observe(wrapper); });
	});

	function mountChart(wrapper, build) {
		pending.set(wrapper, build);
		if (!('IntersectionObserver' in window)) { drawPending(wrapper); return; }
		if (!observer) {
			observer = new IntersectionObserver((entries) => {
				entries.forEach((entry) => {
					if (entry.isIntersecting) { observer.unobserve(entry.target); drawPending(entry.target); }
				});
			}, { rootMargin: '300px 0px' });
		}
		observer.observe(wrapper);
	}

	function drawPending(wrapper) {
		const build = pending.get(wrapper);
		if (!build || !window.echarts) return;
		pending.delete(wrapper);
		const instance = window.echarts.init(wrapper, null, { renderer: 'svg', locale: 'ES' });
		instance.setOption(Object.assign({
			animation: false,
			aria: { enabled: true, decal: { show: false } },
			textStyle: { fontFamily: tok().font, color: tok().ink },
		}, build()));
		charts.push(instance);
	}

	/**
	 * Dibuja todo lo pendiente (PDF, impresión y capturas). Para imprimir se
	 * abren también los «Datos avanzados»: el PDF lleva lo mismo que se ve y
	 * lo que hay detrás de cada acordeón. `{ open: false }` los deja cerrados.
	 */
	function drawAll(options) {
		Array.from(pending.keys()).forEach(drawPending);
		if (!options || options.open !== false) {
			Array.from(unfilled).forEach((d) => d._pgFill());
			document.querySelectorAll('.pg-report details').forEach((d) => { d.open = true; });
		}
		charts.forEach((c) => c.resize());
	}
	window.addEventListener('beforeprint', () => drawAll());
	window.PowerGISReport = { drawAll: drawAll };

	function figure(container, title, text, height) {
		const fig = el('figure', 'pg-figure');
		fig.appendChild(el('figcaption', 'pg-figure__title', title));
		const wrapper = el('div', 'pg-chart');
		wrapper.style.height = height + 'px';
		wrapper.setAttribute('role', 'img');
		wrapper.setAttribute('aria-label', text);
		fig.appendChild(wrapper);
		fig.appendChild(el('p', 'pg-figure__text', text));
		container.appendChild(fig);
		return wrapper;
	}

	/** Leyenda HTML de la valoración: el color nunca va solo. */
	function ratingLegend(ref) {
		const box = el('div', 'pg-rating-legend');
		['favorable', 'media', 'desfavorable'].forEach((r) => box.appendChild(ratingChip(r)));
		if (ref) box.appendChild(el('span', 'pg-muted', refText(ref)));
		return box;
	}

	const PERCENT_STACK = /(_pct)$/;

	/**
	 * Gráfico cuyo eje son las zonas. Barras horizontales, de mayor a menor,
	 * las 15 primeras y la zona analizada; el resto, en «Datos avanzados».
	 */
	function renderZoneChart(container, chart, ctx) {
		const series = chart.series.filter((s) => s.data.some(isNum));
		if (!series.length) return;
		const first = series[0];
		const column = ctx.columns[first.code] || {};
		const ref = series.length === 1 ? column.reference : null;
		const direction = column.direction || 0;
		const decimals = column.decimals === undefined ? 1 : column.decimals;
		const unit = chart.unit;

		let items = chart.x.map((name, i) => ({ name, values: series.map((s) => s.data[i]) }))
			.filter((it) => it.values.some(isNum));
		const stacked = chart.stack && series.length > 1;
		const pctStack = stacked && series.every((s) => PERCENT_STACK.test(s.code));
		items.sort((a, b) => (b.values[0] || 0) - (a.values[0] || 0));
		const total = items.length;
		const top = items.slice(0, 15);
		const own = ctx.ownName && items.find((it) => it.name === ctx.ownName);
		if (own && !top.includes(own)) top.push(own);
		items = top;

		const text = chartSentence(chart.title, items.map((it) => ({ name: it.name, value: it.values[0] })), unit, decimals)
			+ (total > items.length ? ' Se muestran ' + items.length + ' de ' + total + ' zonas; el resto, en «Datos avanzados».' : '');
		if (ref && direction) container.appendChild(ratingLegend(ref));
		const per = stacked || series.length === 1 ? 28 : 14 + 12 * series.length;
		const wrapper = figure(container, chart.title, text, Math.max(160, items.length * per + 70));

		mountChart(wrapper, () => {
			const names = items.map((it) => it.name);
			const own = ctx.ownName;
			// Varias series sin apilar: un color por serie y leyenda; el color de
			// valoración sólo tiene sentido con una serie.
			const multi = stacked || series.length > 1;
			const out = series.map((s, si) => ({
				name: s.name,
				type: 'bar',
				stack: stacked ? 'total' : undefined,
				barMaxWidth: 18,
				data: items.map((it) => {
					const v = it.values[si];
					const r = !multi && direction ? rate(v, ref, direction) : null;
					return {
						value: v,
						itemStyle: multi ? undefined : {
							color: r ? ratingColor(r) : tok().brand,
							borderColor: it.name === own ? tok().ink : undefined,
							borderWidth: it.name === own ? 2 : 0,
						},
						rating: r,
					};
				}),
				label: multi ? undefined : {
					show: true, position: 'right', fontSize: 11, color: tok().ink,
					formatter: (p) => fmt(p.value, unitType(unit), decimals),
				},
			}));
			if (!multi && isNum(ctx.kpiValue(first.code))) {
				out[0].markLine = {
					symbol: 'none', silent: true,
					lineStyle: { color: tok().ink, type: 'dashed' },
					label: { formatter: ctx.ambito, color: tok().ink, fontSize: 11, position: 'end' },
					data: [{ xAxis: ctx.kpiValue(first.code) }],
				};
			}
			return {
				color: tok().cat,
				grid: { left: 8, right: 56, top: multi ? 34 : 22, bottom: 24, containLabel: true },
				legend: multi ? { top: 0, type: 'scroll' } : undefined,
				tooltip: {
					trigger: 'axis', axisPointer: { type: 'shadow' },
					formatter: (params) => {
						const head = params[0] ? params[0].name : '';
						return [head].concat(params.map((p) => {
							const r = p.data && p.data.rating ? ' · ' + RATING[p.data.rating].text : '';
							return p.marker + p.seriesName + ': ' + fmt(p.value, unitType(unit), decimals) + r;
						})).join('<br>');
					},
				},
				xAxis: {
					type: 'value',
					max: pctStack ? 100 : undefined,
					axisLabel: { formatter: (v) => fmt(v, 'int', 0), color: tok().muted },
					splitLine: { lineStyle: { color: tok().line } },
				},
				yAxis: {
					type: 'category', inverse: true, data: names,
					axisLabel: {
						color: tok().ink, width: 140, overflow: 'truncate',
						formatter: (n) => (n === own ? '▶ ' + n : n),
					},
				},
				series: out,
			};
		});
	}

	/** Series en el tiempo o por mes: líneas (o barras verticales para la lluvia). */
	function renderCategoryChart(container, chart) {
		const series = chart.series.filter((s) => s.data.some(isNum)).slice(0, 4);
		if (!series.length) return;
		const type = chart.type === 'line' || chart.type === 'area' ? 'line' : 'bar';
		const unit = chart.unit;
		const items = series[0].data.map((v, i) => ({ name: chart.x[i], value: v }));
		const wrapper = figure(container, chart.title,
			chartSentence(chart.title + ' (' + series[0].name + ')', items, unit, 1), 280);
		mountChart(wrapper, () => ({
			color: tok().cat,
			grid: { left: 8, right: 16, top: 34, bottom: 8, containLabel: true },
			legend: { top: 0, type: 'scroll' },
			tooltip: { trigger: 'axis', valueFormatter: (v) => fmtUnit(v, unit, 1) },
			xAxis: { type: 'category', data: chart.x, axisLabel: { color: tok().muted } },
			yAxis: {
				type: 'value', scale: type === 'line',
				axisLabel: { formatter: (v) => fmt(v, 'float', 0), color: tok().muted },
				splitLine: { lineStyle: { color: tok().line } },
			},
			series: series.map((s, i) => ({
				name: s.name, type: type, data: s.data, connectNulls: false, barMaxWidth: 22,
				symbolSize: 6, lineStyle: { width: i === 0 ? 3 : 2 },
			})),
		}));
	}

	function renderChart(container, chart, ctx) {
		const zones = chart.x.length && chart.x.every((n) => ctx.zoneNames.has(n));
		if (zones && chart.type !== 'line') renderZoneChart(container, chart, ctx);
		else renderCategoryChart(container, chart);
	}

	// ------------------------------------------------------------------ //
	// «Datos avanzados»: tablas completas en acordeón, con marcas y CSV
	// ------------------------------------------------------------------ //

	const PAGE = 50;

	function renderTable(container, table) {
		const box = el('div', 'pg-table');
		box.appendChild(el('h4', 'pg-table__title', table.title));

		const controls = el('div', 'pg-table__controls');
		const searchId = 'pg-s-' + table.id.replace(/[^a-z0-9]/gi, '-');
		const label = el('label', 'pg-sr', 'Filtrar zonas de ' + table.title);
		label.htmlFor = searchId;
		const search = el('input', 'pg-table__search');
		search.type = 'search';
		search.id = searchId;
		search.placeholder = 'Filtrar zonas…';
		controls.appendChild(label);
		controls.appendChild(search);
		const csv = el('button', 'pg-btn pg-btn--ghost');
		csv.type = 'button';
		csv.appendChild(icon('download'));
		csv.appendChild(el('span', null, 'Descargar CSV'));
		csv.addEventListener('click', () => downloadCsv(table));
		controls.appendChild(csv);
		box.appendChild(controls);

		const scroll = el('div', 'pg-table__scroll');
		scroll.tabIndex = 0;
		scroll.setAttribute('role', 'region');
		scroll.setAttribute('aria-label', table.title);
		const element = el('table');
		const thead = el('thead');
		const headRow = el('tr');

		let sortKey = null;
		let sortAsc = false;
		let shown = PAGE;

		table.columns.forEach((column) => {
			const th = el('th', column.type === 'text' ? '' : 'pg-num');
			th.setAttribute('scope', 'col');
			const button = el('button', 'pg-th', column.label);
			button.type = 'button';
			button.addEventListener('click', () => {
				sortAsc = sortKey === column.key ? !sortAsc : false;
				sortKey = column.key;
				headRow.querySelectorAll('th').forEach((h) => h.removeAttribute('aria-sort'));
				th.setAttribute('aria-sort', sortAsc ? 'ascending' : 'descending');
				draw();
			});
			th.appendChild(button);
			headRow.appendChild(th);
		});
		thead.appendChild(headRow);
		element.appendChild(thead);

		const tbody = el('tbody');
		element.appendChild(tbody);
		scroll.appendChild(element);
		box.appendChild(scroll);

		const more = el('button', 'pg-btn pg-table__more', 'Mostrar más zonas');
		more.type = 'button';
		more.addEventListener('click', () => { shown += PAGE; draw(); });
		box.appendChild(more);

		if (table.footnote) box.appendChild(el('p', 'pg-table__note', table.footnote));

		const tops = new Set(table.highlights && table.highlights.top || []);
		const bottoms = new Set(table.highlights && table.highlights.bottom || []);

		function draw() {
			const needle = search.value.trim().toLowerCase();
			let rows = table.rows.filter((row) =>
				!needle || String(row.zona || '').toLowerCase().includes(needle));
			if (sortKey) {
				rows = rows.slice().sort((a, b) => {
					const x = a[sortKey];
					const y = b[sortKey];
					if (x === null || x === undefined) return 1;
					if (y === null || y === undefined) return -1;
					if (typeof x === 'number' && typeof y === 'number') return sortAsc ? x - y : y - x;
					return sortAsc ? String(x).localeCompare(String(y), 'es') : String(y).localeCompare(String(x), 'es');
				});
			}
			more.hidden = rows.length <= shown;
			tbody.innerHTML = '';
			rows.slice(0, shown).forEach((row) => {
				const tr = el('tr');
				table.columns.forEach((column) => {
					const value = row[column.key];
					const td = el('td', column.type === 'text' ? '' : 'pg-num');
					if (column.type === 'text') {
						td.textContent = value;
						if (tops.has(row.geo_code)) td.appendChild(el('span', 'pg-tag pg-tag--top', 'Destacada'));
						else if (bottoms.has(row.geo_code)) td.appendChild(el('span', 'pg-tag', 'A la cola'));
					} else if (value === null || value === undefined) {
						td.className += ' pg-na';
						td.textContent = '—';
						td.title = 'Sin dato';
						td.appendChild(el('span', 'pg-sr', 'Sin dato'));
					} else {
						const flags = (row._flags || {})[column.key] || [];
						const r = (flags.includes('heredado') || flags.includes('heredado_municipio')) ? null : rate(value, column.reference, column.direction);
						if (r) {
							const ic = icon(RATING[r].icon);
							ic.className += ' pg-cell-rating pg-cell-rating--' + r;
							td.appendChild(ic);
							td.title = RATING[r].text;
						}
						td.appendChild(document.createTextNode(fmt(value, column.type, column.decimals)));
						if (r) td.appendChild(el('span', 'pg-sr', ' (' + RATING[r].text + ')'));
						flags.forEach((flag) => {
							const f = FLAGS[flag];
							if (!f) return;
							const mark = icon(f.icon);
							mark.className += ' pg-cell-flag';
							td.appendChild(mark);
							td.appendChild(el('span', 'pg-sr', ' (' + f.text + ')'));
							td.title = (td.title ? td.title + ' · ' : '') + f.text;
						});
					}
					tr.appendChild(td);
				});
				tbody.appendChild(tr);
			});
		}

		search.addEventListener('input', () => { shown = PAGE; draw(); });
		draw();
		container.appendChild(box);
	}

	function downloadCsv(table) {
		const esc = (v) => {
			const s = v === null || v === undefined ? '' : (typeof v === 'number'
				? String(v).replace('.', ',') : String(v));
			return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
		};
		const lines = [table.columns.map((c) => esc(c.label)).join(';')];
		table.rows.forEach((row) => lines.push(table.columns.map((c) => esc(row[c.key])).join(';')));
		const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
		const a = el('a');
		a.href = URL.createObjectURL(blob);
		a.download = (table.id || 'tabla') + '.csv';
		document.body.appendChild(a);
		a.click();
		setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
	}

	// El contenido de «Datos avanzados» se construye al abrirlo: con 180 zonas
	// y una tabla por subsección, pintarlo todo de entrada bloqueaba el móvil.
	const unfilled = new Set();

	function advanced(container, title, fill) {
		const details = el('details', 'pg-advanced');
		const summary = el('summary', null, 'Datos avanzados · ' + title);
		details.appendChild(summary);
		const run = () => {
			if (!unfilled.delete(details)) return;
			fill(details);
		};
		details._pgFill = run;
		unfilled.add(details);
		details.addEventListener('toggle', () => { if (details.open) run(); });
		container.appendChild(details);
		return details;
	}

	// ------------------------------------------------------------------ //
	// Mapa (ECharts + recintos IGN simplificados, clases por quintiles)
	// ------------------------------------------------------------------ //

	const RATE_UNITS = new Set(['%', '‰', 'indice', 'ratio', 'EUR', 'años', '°C', 'mm', 'h', 'días']);
	const DIVERGING = new Set(['mov.interprov.net_rate', 'inm.price.yoy_change', 'inm.ipv.yoy', 'inm.rent.ipva_yoy']);
	const geoCache = {};

	function geoFiles(level, codes) {
		if (level === 'ccaa') return ['ccaa.json'];
		if (level === 'provincia') return ['provincias.json'];
		if (level === 'municipio') {
			return Array.from(new Set(codes.map((c) => c.slice(0, 2)))).map((p) => 'municipios-' + p + '.json');
		}
		return [];
	}

	async function loadGeo(files) {
		const base = CFG.geoUrl || '';
		const parts = await Promise.all(files.map((f) => {
			if (!geoCache[f]) {
				geoCache[f] = fetch(base + f, { credentials: 'same-origin' }).then((r) => {
					if (!r.ok) throw new Error(f + ': ' + r.status);
					return r.json();
				});
			}
			return geoCache[f];
		}));
		return { type: 'FeatureCollection', features: parts.flatMap((p) => p.features) };
	}

	/** Cortes por quintiles (o un corte por valor si hay menos de 5 distintos). */
	function classes(values, diverging) {
		const vals = values.filter(isNum).sort((a, b) => a - b);
		if (!vals.length) return [];
		if (diverging) {
			const m = Math.max(Math.abs(vals[0]), Math.abs(vals[vals.length - 1])) || 1;
			const c = [-m, -0.6 * m, -0.2 * m, 0.2 * m, 0.6 * m, m];
			return c.slice(0, 5).map((min, i) => ({ min: min, max: c[i + 1] }));
		}
		const distinct = Array.from(new Set(vals));
		if (distinct.length <= 5) return distinct.map((v) => ({ min: v, max: v }));
		const q = (p) => {
			const pos = (vals.length - 1) * p;
			const lo = Math.floor(pos);
			return vals[lo] + (vals[Math.min(lo + 1, vals.length - 1)] - vals[lo]) * (pos - lo);
		};
		const cuts = [vals[0], q(0.2), q(0.4), q(0.6), q(0.8), vals[vals.length - 1]];
		return [0, 1, 2, 3, 4].map((i) => ({ min: cuts[i], max: cuts[i + 1] }));
	}

	function renderMap(container, geolens, ctx) {
		if (!geolens || !geolens.layers || !geolens.layers.length) return;
		const layers = geolens.layers.filter((l) => RATE_UNITS.has(l.unit)
			&& Object.values(l.values || {}).some(isNum));
		if (!layers.length) return;

		const section = el('section', 'pg-geolens');
		section.id = 'geolens';
		section.appendChild(el('h2', null, 'Mapa del ámbito'));

		const bar = el('div', 'pg-geolens__bar');
		const selectId = 'pg-map-layer';
		const label = el('label', 'pg-geolens__label', 'Indicador del mapa');
		label.htmlFor = selectId;
		const select = el('select', 'pg-select');
		select.id = selectId;
		const byId = {};
		layers.forEach((l) => { byId[l.id] = l; });
		const grouped = new Set();
		Object.keys(geolens.groups || {}).forEach((group) => {
			const og = el('optgroup');
			og.label = group.charAt(0).toUpperCase() + group.slice(1);
			(geolens.groups[group] || []).forEach((id) => {
				const l = byId[id];
				if (!l) return;
				grouped.add(id);
				const distinct = new Set(Object.values(l.values).filter(isNum)).size;
				const opt = el('option', null, l.label + (distinct <= 1 ? ' (mismo valor en todas las zonas)' : ''));
				opt.value = id;
				opt.disabled = distinct <= 1;
				og.appendChild(opt);
			});
			if (og.children.length) select.appendChild(og);
		});
		layers.filter((l) => !grouped.has(l.id)).forEach((l) => {
			const opt = el('option', null, l.label);
			opt.value = l.id;
			select.appendChild(opt);
		});
		const preferred = layers.find((l) => l.default_on && Object.values(l.values).some(isNum))
			|| layers.find((l) => l.id === 'dem.pop.segment_pct') || layers[0];
		select.value = preferred.id;
		bar.appendChild(label);
		bar.appendChild(select);
		section.appendChild(bar);

		const legend = el('div', 'pg-legend');
		legend.setAttribute('aria-live', 'polite');
		const mapBox = el('div', 'pg-geolens__map');
		mapBox.setAttribute('role', 'img');
		section.appendChild(legend);
		section.appendChild(mapBox);
		section.appendChild(el('p', 'pg-geolens__attr',
			'Recintos: © Instituto Geográfico Nacional (CC BY 4.0), vía es-atlas, simplificados. '
			+ 'Fuentes de los datos: ver «Fuentes y metodología».'));
		const tableBox = el('div');
		let tableFn = null;
		advanced(section, 'valores del mapa en tabla', (d) => {
			d.appendChild(tableBox);
			tableBox.dataset.ready = '1';
			if (tableFn) tableFn();
		});
		container.appendChild(section);

		const codes = Object.keys(preferred.values);
		const files = geoFiles(geolens.level, codes);
		let chart = null;
		const mapName = 'pg-' + geolens.level + '-' + files.join('-');

		function paint(layer) {
			const diverging = DIVERGING.has(layer.id);
			const ramp = diverging ? tok().div : tok().seq;
			const values = Object.values(layer.values);
			const cls = classes(values, diverging);
			const colorOf = (i) => (cls.length < 5 && !diverging ? ramp[Math.min(4, i + (5 - cls.length))] : ramp[i]);
			const decimals = layer.unit === 'EUR' ? 0 : 1;
			const pieces = cls.map((c, i) => ({
				min: c.min, max: c.max, color: colorOf(i),
				label: c.min === c.max ? fmtUnit(c.min, layer.unit, decimals)
					: fmtUnit(c.min, layer.unit, decimals) + ' – ' + fmtUnit(c.max, layer.unit, decimals),
			}));
			const classOf = (v) => {
				if (!isNum(v)) return -1;
				const i = cls.findIndex((c) => v >= c.min && v <= c.max);
				return i < 0 ? (v < cls[0].min ? 0 : cls.length - 1) : i;
			};

			// Leyenda en HTML: rango + muestra, y «Sin dato» con trama.
			legend.innerHTML = '';
			legend.appendChild(el('div', 'pg-legend__title',
				layer.label + ' · ' + (diverging ? 'negativo ← 0 → positivo' : 'más claro = menos · más oscuro = más')));
			pieces.forEach((p, i) => {
				const item = el('span', 'pg-legend__item');
				const sw = el('span', 'pg-legend__swatch');
				sw.style.background = p.color;
				item.appendChild(sw);
				item.appendChild(el('span', null, (cls.length === 5 && !diverging ? 'Quintil ' + (i + 1) + ': ' : '') + p.label));
				legend.appendChild(item);
			});
			const na = el('span', 'pg-legend__item');
			na.appendChild(el('span', 'pg-legend__swatch pg-legend__swatch--na'));
			na.appendChild(el('span', null, 'Sin dato'));
			legend.appendChild(na);

			const entries = Object.keys(layer.values).map((code) => ({ code, value: layer.values[code] }));
			const named = entries.map((e) => ({ name: e.code, value: e.value, label: ctx.codeNames[e.code] || e.code }));
			const sorted = named.filter((e) => isNum(e.value)).sort((a, b) => b.value - a.value);
			mapBox.setAttribute('aria-label', 'Mapa de ' + layer.label + '. ' + (sorted.length
				? 'Valor más alto: ' + sorted[0].label + ' (' + fmtUnit(sorted[0].value, layer.unit, decimals)
				+ '); más bajo: ' + sorted[sorted.length - 1].label + ' (' + fmtUnit(sorted[sorted.length - 1].value, layer.unit, decimals) + ').'
				: 'Sin datos.'));

			tableFn = () => { tableBox.innerHTML = ''; renderTable(tableBox, {
				id: 'mapa-' + layer.id, title: layer.label,
				columns: [{ key: 'zona', label: 'Zona', type: 'text' },
					{ key: 'v', label: layer.label, type: unitType(layer.unit), decimals: decimals },
					{ key: 'clase', label: 'Clase', type: 'text' }],
				rows: named.map((e) => ({
					zona: e.label, v: e.value, geo_code: e.name,
					clase: isNum(e.value) ? pieces[classOf(e.value)].label : 'Sin dato',
				})),
			}); };
			if (tableBox.dataset.ready) tableFn();

			if (!chart) return;
			chart.setOption({
				tooltip: {
					trigger: 'item',
					formatter: (p) => {
						const v = layer.values[p.name];
						const k = classOf(v);
						return (ctx.codeNames[p.name] || (p.data && p.data.label) || p.name) + '<br>'
							+ layer.label + ': ' + fmtUnit(v, layer.unit, decimals)
							+ (k >= 0 ? '<br>Clase: ' + pieces[k].label : '');
					},
				},
				series: [{
					type: 'map', map: mapName, nameProperty: 'ine_code', roam: true,
					aspectScale: 0.8, selectedMode: false,
					itemStyle: { areaColor: tok().nodata, borderColor: '#ffffff', borderWidth: 0.6,
						decal: { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: -0.8, color: 'rgba(0,0,0,0.12)' } },
					emphasis: { label: { show: false }, itemStyle: { areaColor: tok().fav, borderColor: tok().ink } },
					label: { show: false },
					data: named.filter((e) => isNum(e.value)).map((e) => ({
						name: e.name, value: e.value, label: e.label,
						itemStyle: { areaColor: pieces[classOf(e.value)].color, decal: { symbol: 'none' } },
					})),
				}],
			}, { replaceMerge: ['series'] });
		}

		mapBox.style.height = 'min(70vh, 520px)';
		Promise.all([loadGeo(files), echartsReady]).then(([geojson]) => {
			if (!window.echarts) throw new Error('sin ECharts');
			geojson.features.forEach((f) => { ctx.codeNames[f.properties.ine_code] = ctx.codeNames[f.properties.ine_code] || f.properties.name; });
			window.echarts.registerMap(mapName, geojson);
			mountChart(mapBox, () => ({}));
			drawPending(mapBox);
			chart = charts[charts.length - 1];
			paint(byId[select.value]);
		}).catch((error) => {
			console.warn('[powergis] mapa sin geometrías:', error);
			mapBox.removeAttribute('role');
			mapBox.style.height = 'auto';
			mapBox.appendChild(el('p', 'pg-notice', 'El mapa no se ha podido dibujar (faltan los recintos de este nivel). Los valores están en la tabla de «Datos avanzados».'));
			paint(byId[select.value]);
		});
		paint(byId[select.value]);
		select.addEventListener('change', () => paint(byId[select.value]));
	}

	// ------------------------------------------------------------------ //
	// Renta frente a público objetivo (dispersión con cuadrantes)
	// ------------------------------------------------------------------ //

	function findTable(payload, sectionId, tableId) {
		const section = (payload.sections || []).find((s) => s.id === sectionId && s.available);
		if (!section) return null;
		for (const sub of section.subsections || []) {
			const t = (sub.tables || []).find((x) => x.id === tableId);
			if (t) return t;
		}
		return null;
	}

	function median(values) {
		const v = values.filter(isNum).sort((a, b) => a - b);
		if (!v.length) return null;
		const m = Math.floor(v.length / 2);
		return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
	}

	function renderScatter(container, payload, ctx) {
		const renta = findTable(payload, 'socioeconomico', 'eco.tabla_renta');
		const edad = findTable(payload, 'demografia', 'dem.tabla_edad');
		if (!renta || !edad) return;
		const pub = {};
		edad.rows.forEach((r) => { pub[r.geo_code] = r['dem.pop.segment_pct']; });
		const points = renta.rows.map((r) => ({ name: r.zona, x: r['eco.income.household.mean'], y: pub[r.geo_code] }))
			.filter((p) => isNum(p.x) && isNum(p.y));
		if (points.length < 3) return;
		const mx = median(points.map((p) => p.x));
		const my = median(points.map((p) => p.y));
		const quad = (p) => (p.x >= mx && p.y >= my ? 'favorable' : (p.x < mx && p.y < my ? 'desfavorable' : 'media'));
		const best = points.filter((p) => quad(p) === 'favorable');
		const text = best.length + ' de ' + points.length + ' zonas tienen a la vez más público objetivo y más renta que la mediana de '
			+ ctx.ambito + (best.length ? ': ' + listText(best.slice(0, 5).map((p) => p.name)) + (best.length > 5 ? '…' : '') : '') + '.';
		container.appendChild(ratingLegend(null));
		const wrapper = figure(container, 'Renta media por hogar frente a peso del público objetivo', text, 360);
		const SYMBOL = { favorable: 'circle', media: 'diamond', desfavorable: 'triangle' };
		mountChart(wrapper, () => ({
			grid: { left: 8, right: 24, top: 36, bottom: 30, containLabel: true },
			tooltip: {
				trigger: 'item',
				formatter: (p) => p.data.name + '<br>Renta: ' + fmt(p.data.value[0], 'eur', 0)
					+ '<br>Público objetivo: ' + fmt(p.data.value[1], 'pct', 1) + '<br>' + RATING[p.data.q].text,
			},
			xAxis: { type: 'value', scale: true, name: 'Renta bruta media por hogar (€)', nameLocation: 'middle', nameGap: 28,
				axisLabel: { formatter: (v) => fmt(v, 'int', 0), color: tok().muted }, splitLine: { lineStyle: { color: tok().line } } },
			yAxis: { type: 'value', scale: true, name: 'Público objetivo (%)', nameTextStyle: { align: 'left' },
				axisLabel: { formatter: (v) => fmt(v, 'float', 0), color: tok().muted }, splitLine: { lineStyle: { color: tok().line } } },
			series: [{
				type: 'scatter', symbolSize: 10,
				data: points.map((p) => ({ name: p.name, value: [p.x, p.y], q: quad(p), symbol: SYMBOL[quad(p)],
					itemStyle: { color: ratingColor(quad(p)), borderColor: p.name === ctx.ownName ? tok().ink : '#fff', borderWidth: p.name === ctx.ownName ? 2 : 0.5 } })),
				markLine: { symbol: 'none', silent: true, lineStyle: { color: tok().muted, type: 'dashed' },
					label: { show: false }, data: [{ xAxis: mx }, { yAxis: my }] },
			}],
		}));
	}

	// ------------------------------------------------------------------ //
	// PlaceRank
	// ------------------------------------------------------------------ //

	const scoreRating = (s) => (!isNum(s) ? null : (s >= 70 ? 'favorable' : (s >= 40 ? 'media' : 'desfavorable')));

	function renderPlaceRank(container, placerank, postId, ctx) {
		if (!placerank || !placerank.rows || !placerank.rows.length) return;

		const section = el('section', 'pg-placerank');
		section.id = 'placerank';
		section.appendChild(el('h2', null, 'PlaceRank: ¿qué zonas encajan mejor?'));
		const first = placerank.rows[0];
		section.appendChild(el('p', 'pg-lead', first.geo_name + ' es la zona mejor puntuada (' + fmt(first.score, 'float', 1)
			+ ' sobre 100, ' + String(first.category || '').toLowerCase() + ')'
			+ (placerank.rows.length > 2 ? '. Le siguen ' + placerank.rows[1].geo_name + ' y ' + placerank.rows[2].geo_name + '.' : '.')));

		const chartBox = el('div');
		section.appendChild(chartBox);
		const drawChart = (rows) => {
			chartBox.innerHTML = '';
			const items = rows.slice(0, 15);
			const wrapper = figure(chartBox, 'Puntuación PlaceRank (0–100)', chartSentence('Puntuación PlaceRank',
				items.map((r) => ({ name: r.geo_name, value: r.score })), 'indice', 1), items.length * 28 + 60);
			chartBox.insertBefore(ratingLegend(null), chartBox.firstChild);
			mountChart(wrapper, () => ({
				grid: { left: 8, right: 48, top: 8, bottom: 24, containLabel: true },
				tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
					formatter: (p) => p[0].name + ': ' + fmt(p[0].value, 'float', 1) + ' · ' + (RATING[scoreRating(p[0].value)] || {}).text },
				xAxis: { type: 'value', max: 100, axisLabel: { color: tok().muted }, splitLine: { lineStyle: { color: tok().line } } },
				yAxis: { type: 'category', inverse: true, data: items.map((r) => r.geo_name),
					axisLabel: { color: tok().ink, width: 140, overflow: 'truncate' } },
				series: [{ type: 'bar', barMaxWidth: 18,
					data: items.map((r) => ({ value: r.score, itemStyle: { color: ratingColor(scoreRating(r.score)) } })),
					label: { show: true, position: 'right', fontSize: 11, formatter: (p) => fmt(p.value, 'float', 1) },
					markLine: { symbol: 'none', silent: true, label: { show: false }, lineStyle: { color: tok().muted, type: 'dashed' }, data: [{ xAxis: 50 }] } }],
			}));
		};

		const table = el('div');
		const redraw = (rows) => { drawChart(rows); drawRank(table, rows); };

		if (!SHARED) {
			// Ajuste de pesos en vivo: el backend reutiliza las dimensiones ya
			// calculadas, así que responde al instante.
			const sliders = el('div', 'pg-weights');
			Object.keys(placerank.weights || {}).forEach((key) => {
				const row = el('label', 'pg-weight');
				row.appendChild(el('span', 'pg-weight__label', key));
				const input = el('input');
				input.type = 'range';
				input.min = '0';
				input.max = '100';
				input.value = String(Math.round(placerank.weights[key] * 100));
				input.dataset.key = key;
				input.setAttribute('aria-label', 'Peso de ' + key);
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
						redraw(updated.rows);
					} catch (error) {
						console.warn('[powergis] no se pudo recalcular el PlaceRank', error);
					}
				});
				row.appendChild(input);
				row.appendChild(out);
				sliders.appendChild(row);
			});
			section.appendChild(sliders);
		}
		advanced(section, 'ranking completo y dimensiones', (d) => {
			d.appendChild(el('p', 'pg-muted', placerank.method));
			d.appendChild(table);
		});
		redraw(placerank.rows);
		container.appendChild(section);
	}

	function drawRank(container, rows) {
		container.innerHTML = '';
		const scroll = el('div', 'pg-table__scroll');
		scroll.tabIndex = 0;
		scroll.setAttribute('role', 'region');
		scroll.setAttribute('aria-label', 'Ranking PlaceRank');
		const element = el('table', 'pg-rank');
		const thead = el('thead');
		const head = el('tr');
		['#', 'Zona', 'Puntuación', 'Valoración', 'Económico', 'Demográfico', 'Ambiental', 'Encaje con tu perfil']
			.forEach((label) => { const th = el('th', null, label); th.setAttribute('scope', 'col'); head.appendChild(th); });
		thead.appendChild(head);
		element.appendChild(thead);
		const tbody = el('tbody');
		rows.forEach((row) => {
			const tr = el('tr');
			tr.appendChild(el('td', 'pg-num', row.rank));
			tr.appendChild(el('td', null, row.geo_name));
			tr.appendChild(el('td', 'pg-num pg-strong', fmt(row.score, 'float', 1)));
			const cat = el('td');
			const chip = ratingChip(scoreRating(row.score));
			if (chip) cat.appendChild(chip);
			cat.appendChild(el('span', 'pg-muted', ' ' + (row.category || '')));
			tr.appendChild(cat);
			['economico', 'demografico', 'ambiental', 'match'].forEach((key) => {
				tr.appendChild(el('td', 'pg-num', fmt((row.dimensions || {})[key], 'float', 1)));
			});
			if (row.narrative) tr.title = row.narrative;
			tbody.appendChild(tr);
		});
		element.appendChild(tbody);
		scroll.appendChild(element);
		container.appendChild(scroll);
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

	/** Lo que necesitan los gráficos y textos de todo el informe, leído una vez. */
	function buildContext(payload) {
		const scope = payload.scope || {};
		const ctx = {
			ambito: scope.name || 'el ámbito',
			ownName: null,
			zoneNames: new Set(),
			codeNames: {},
			columns: {},
			kpis: {},
			kpiValue: (code) => (ctx.kpis[code] ? ctx.kpis[code].value : null),
		};
		(payload.sections || []).filter((s) => s.available).forEach((section) => {
			(section.subsections || []).forEach((sub) => {
				(sub.kpis || []).forEach((k) => { if (!ctx.kpis[k.code]) ctx.kpis[k.code] = k; });
				(sub.tables || []).forEach((table) => {
					table.columns.forEach((c) => { if (!ctx.columns[c.key]) ctx.columns[c.key] = c; });
					table.rows.forEach((r) => {
						if (r.zona) ctx.zoneNames.add(r.zona);
						if (r.geo_code) ctx.codeNames[r.geo_code] = r.zona;
					});
				});
			});
		});
		// Ámbito municipal: el municipio se compara con los de su provincia y
		// sale entre ellos; se resalta en los gráficos.
		if (scope.level === 'municipio' && scope.name && ctx.zoneNames.has(scope.name)) ctx.ownName = scope.name;
		return ctx;
	}

	function renderQuality(root, payload) {
		const warnings = payload.warnings || [];
		const cover = (payload.executive_summary || {}).cobertura || {};
		const titles = {};
		(payload.sections || []).forEach((s) => { titles[s.id] = s.title; });
		const low = Object.keys(cover).filter((id) => cover[id] < 1);
		if (!warnings.length && !low.length) return;
		const box = el('details', 'pg-advanced pg-quality');
		box.appendChild(el('summary', null, 'Calidad de los datos · ' + (warnings.length
			? warnings.length + (warnings.length === 1 ? ' aviso' : ' avisos') : 'cobertura por sección')));
		warnings.forEach((w) => box.appendChild(el('p', 'pg-warning', w)));
		if (low.length) {
			const list = el('ul', 'pg-quality__list');
			low.forEach((id) => list.appendChild(el('li', null, (titles[id] || id) + ': '
				+ fmt(cover[id] * 100, 'int') + ' % de los indicadores con dato')));
			box.appendChild(list);
		}
		root.appendChild(box);
	}

	function renderSummary(root, payload, ctx) {
		const summary = payload.executive_summary;
		if (!summary) return;
		const box = el('section', 'pg-summary');
		box.id = 'pg-resumen';
		box.appendChild(el('h2', null, 'Resumen ejecutivo'));
		const share = ctx.kpis['dem.pop.segment_pct'];
		const tiles = (summary.headline || []).map((item) => {
			const tile = {
				label: item.label, value: item.value, unit: item.unit,
				decimals: item.unit === '%' ? 1 : 0, missing: item.value === null,
			};
			// El peso del público objetivo lleva su valoración (la del KPI de demografía).
			if (item.unit === '%' && share && !share.missing) {
				Object.assign(tile, { rating: share.rating, reference: share.reference, flags: share.flags });
			} else if (item.unit === '%') {
				// Sin tarjeta propia: se valora con la referencia de su columna.
				const col = ctx.columns['dem.pop.segment_pct'];
				if (col && col.reference) {
					Object.assign(tile, { rating: rate(item.value, col.reference, col.direction || 1), reference: col.reference });
				}
			}
			return tile;
		});
		const get = (unit, i) => (summary.headline || []).filter((h) => h.unit === unit)[i || 0] || {};
		const pop = get('personas', 0).value;
		const seg = get('personas', 1).value;
		const pct = get('%').value;
		const parts = [];
		if (isNum(pop)) {
			parts.push('En ' + ctx.ambito + ' viven ' + fmt(pop, 'int') + ' personas'
				+ (isNum(seg) ? '; ' + fmt(seg, 'int') + ' forman tu público objetivo'
				+ (isNum(pct) ? ' (' + fmt(pct, 'pct', 1) + ')' : '') : '') + '.');
		}
		const pctTile = tiles.find((t) => t.unit === '%');
		if (pctTile && pctTile.rating && pctTile.reference) {
			parts.push('Es ' + FRASE[pctTile.rating] + ' frente a ' + baseText(pctTile.reference) + '.');
		}
		const best = (summary.mejores_zonas || []).map((z) => z.zona).filter(Boolean);
		if (best.length) parts.push('Las zonas que mejor encajan: ' + listText(best) + '.');
		if (parts.length) box.appendChild(el('p', 'pg-lead', parts.join(' ')));
		renderKpis(box, tiles);
		const narrative = summary.narrative;
		if (narrative && narrative.resumen) box.appendChild(el('p', null, narrative.resumen));
		root.appendChild(box);
	}

	function renderCross(root, payload, ctx) {
		const box = el('section', 'pg-cross');
		box.id = 'pg-cruce';
		box.appendChild(el('h2', null, 'Dónde coinciden renta y público objetivo'));
		renderScatter(box, payload, ctx);
		if (box.querySelector('.pg-figure')) root.appendChild(box);
	}

	function renderSources(root, payload) {
		const sources = payload.sources || [];
		const glossary = payload.glossary || [];
		if (!sources.length && !glossary.length) return;
		const box = el('section', 'pg-sources');
		box.id = 'pg-fuentes';
		box.appendChild(el('h2', null, 'Fuentes y metodología'));
		const legend = el('div', 'pg-flag-legend');
		legend.appendChild(el('p', null, 'Cómo leer las etiquetas de los datos:'));
		const list = el('ul');
		Object.keys(FLAGS).forEach((flag) => {
			const li = el('li');
			li.appendChild(flagChips([flag]));
			li.appendChild(el('span', null, ' ' + FLAGS[flag].tip));
			list.appendChild(li);
		});
		const how = el('li');
		how.appendChild(ratingLegend(null));
		how.appendChild(el('span', null, 'Favorable o desfavorable compara con las zonas del informe: por encima del percentil 75 o por debajo del 25. Con menos de 5 zonas, con el total nacional (±5 %).'));
		list.appendChild(how);
		legend.appendChild(list);
		box.appendChild(legend);
		advanced(box, 'fuentes y glosario', (d) => {
			if (sources.length) {
				const ul = el('ul');
				sources.forEach((s) => ul.appendChild(el('li', null, s.name + ' — ' + s.attribution)));
				d.appendChild(ul);
			}
			if (glossary.length) {
				const dl = el('dl', 'pg-glossary');
				glossary.forEach((g) => {
					dl.appendChild(el('dt', null, g.term || g.label || g.code));
					dl.appendChild(el('dd', null, g.definition || g.description || ''));
				});
				d.appendChild(dl);
			}
		});
		root.appendChild(box);
	}

	function renderReport(root, payload) {
		root.innerHTML = '';
		const ctx = buildContext(payload);

		renderQuality(root, payload);
		renderSummary(root, payload, ctx);
		renderMap(root, payload.geolens, ctx);
		renderCross(root, payload, ctx);

		const locked = [];
		// Interruptores del formulario («Incluir nivel turístico»…). El motor
		// ya no manda lo apagado; esto cubre los informes guardados antes.
		const layers = payload.layers || {};
		const layerOff = (key) => Boolean(key) && layers[key] === false;

		(payload.sections || []).forEach((section) => {
			const subsections = (section.subsections || []).filter((sub) => !layerOff(sub.layer));
			if (section.available && section.subsections && section.subsections.length && !subsections.length) {
				return;   // todas sus capas apagadas: la sección no se pinta
			}
			if (!section.available) {
				if (SHARED) return;   // al invitado no se le vende nada
				locked.push(section);
				renderLockedMarker(root, section);
				return;
			}
			const box = el('section', 'pg-section');
			box.id = 'seccion-' + section.id;
			box.appendChild(el('h2', null, section.title));
			// El motivo de lo que falta va dentro de la sección, no sólo arriba.
			(section.notes || []).forEach((note) => box.appendChild(el('p', 'pg-warning', note)));

			subsections.forEach((sub) => {
				box.appendChild(el('h3', null, sub.title));
				const text = sub.narrative || subsectionText(sub, ctx);
				if (text) box.appendChild(el('p', 'pg-sub__text', text));
				renderKpis(box, sub.kpis);
				(sub.charts || []).forEach((chart) => renderChart(box, chart, ctx));
				if ((sub.tables || []).length) {
					advanced(box, sub.title, (d) => sub.tables.forEach((t) => renderTable(d, t)));
				}
			});
			root.appendChild(box);
		});

		renderPlaceRank(root, payload.placerank, CFG.postId, ctx);
		renderConclusions(root, payload.executive_summary);
		renderUpgradePanel(root, locked, CFG.postId);
		renderSources(root, payload);

		let timer = null;
		window.addEventListener('resize', () => {
			clearTimeout(timer);
			timer = setTimeout(() => charts.forEach((chart) => chart.resize()), 150);
		});

		if (payload.scope && payload.scope.name) {
			document.querySelectorAll('[data-pg-scope-name]').forEach((node) => {
				node.textContent = payload.scope.name;
			});
		}
		buildToc(root);
		loadEcharts();
	}

	// ------------------------------------------------------------------ //
	// Conclusiones
	// ------------------------------------------------------------------ //

	/**
	 * Cierre del informe: lo que dice la IA (si ha llegado) y las mejores y
	 * peores zonas del resumen determinista, que existen siempre.
	 */
	function renderConclusions(container, summary) {
		if (!summary) return;
		const narrative = summary.narrative || {};
		const best = summary.mejores_zonas || [];
		const worst = summary.peores_zonas || [];
		const hasText = narrative.recomendacion
			|| (narrative.fortalezas || []).length || (narrative.riesgos || []).length;
		if (!hasText && !best.length && !worst.length) return;

		const box = el('section', 'pg-conclusions');
		box.id = 'pg-conclusiones';
		box.appendChild(el('h2', null, 'Conclusiones'));

		const block = (title, items, render) => {
			if (!items.length) return;
			const part = el('div', 'pg-conclusions__block');
			part.appendChild(el('h3', null, title));
			const list = el('ul');
			items.forEach((item) => list.appendChild(el('li', null, render(item))));
			part.appendChild(list);
			box.appendChild(part);
		};
		const zone = (row) => row.zona
			+ (row.score !== undefined ? ' · ' + fmt(row.score, 'float', 1) : '');

		block('Fortalezas', narrative.fortalezas || [], String);
		block('Riesgos', narrative.riesgos || [], String);
		block('Zonas más favorables', best, zone);
		block('Zonas menos favorables', worst, zone);

		if (narrative.recomendacion) {
			const part = el('div', 'pg-conclusions__block');
			part.appendChild(el('h3', null, 'Recomendación'));
			part.appendChild(el('p', null, narrative.recomendacion));
			box.appendChild(part);
		}
		container.appendChild(box);
	}

	// ------------------------------------------------------------------ //
	// Navegación: X, «Mis proyectos» y panel de control
	// ------------------------------------------------------------------ //

	/**
	 * Índice jerárquico del panel, a partir de lo que se ha pintado: un nivel
	 * por sección (h2) y otro por subsección (h3). Así no hay que mantener
	 * una lista aparte cuando el motor añade secciones.
	 */
	function buildToc(root) {
		const toc = document.querySelector('[data-pg-toc]');
		if (!toc) return;
		toc.innerHTML = '';

		const list = el('ol', 'pg-toc__list');
		root.querySelectorAll(':scope > section[id]').forEach((section) => {
			const heading = section.querySelector('h2');
			if (!heading) return;
			const item = el('li');
			const link = el('a', 'pg-toc__link', heading.textContent);
			link.href = '#' + section.id;
			link.dataset.pgJump = '';
			item.appendChild(link);
			if (section.classList.contains('pg-locked')) {
				item.appendChild(el('span', 'pg-toc__badge', T.inAdvanced || 'Avanzado'));
			}

			const subs = section.querySelectorAll(':scope > h3');
			if (subs.length) {
				const sublist = el('ol', 'pg-toc__sub');
				subs.forEach((sub, index) => {
					if (!sub.id) sub.id = section.id + '-' + (index + 1);
					const subItem = el('li');
					const subLink = el('a', 'pg-toc__link', sub.textContent);
					subLink.href = '#' + sub.id;
					subLink.dataset.pgJump = '';
					subItem.appendChild(subLink);
					sublist.appendChild(subItem);
				});
				item.appendChild(sublist);
			}
			list.appendChild(item);
		});

		if (!list.children.length) {
			toc.appendChild(el('p', 'pg-muted', T.indexEmpty || ''));
			return;
		}
		toc.appendChild(list);
		syncJumps();
	}

	/**
	 * Accesos directos del panel. En el informe básico GeoLens y PlaceRank no
	 * se pintan: el acceso lleva al panel de compra en vez de a ninguna parte.
	 */
	function syncJumps() {
		document.querySelectorAll('.pg-jump').forEach((link) => {
			const target = link.dataset.pgTarget || link.getAttribute('href');
			link.dataset.pgTarget = target;
			const exists = document.querySelector(target);
			const upgrade = document.getElementById('pg-upgrade');
			link.classList.toggle('is-locked', !exists && !!upgrade);
			if (exists) {
				link.setAttribute('href', target);
				link.removeAttribute('aria-disabled');
			} else if (upgrade) {
				link.setAttribute('href', '#pg-upgrade');
				link.removeAttribute('aria-disabled');
			} else {
				link.setAttribute('aria-disabled', 'true');
			}
		});
	}

	function initNav() {
		const dock = document.querySelector('[data-pg-dock]');
		if (!dock) return;

		// X: vuelve a la página anterior si es de esta web; si no hay, a la
		// portada (el href del enlace).
		const close = dock.querySelector('[data-pg-close]');
		if (close) {
			close.addEventListener('click', (event) => {
				let sameSite = false;
				try {
					const from = new URL(document.referrer);
					sameSite = from.origin === window.location.origin
						&& from.pathname !== window.location.pathname;
				} catch (e) { /* sin referrer */ }
				if (sameSite && window.history.length > 1) {
					event.preventDefault();
					window.history.back();
				}
			});
		}

		// «Mis proyectos»
		const menu = dock.querySelector('[data-pg-projects]');
		const toggle = dock.querySelector('[data-pg-projects-toggle]');
		const pop = menu && menu.querySelector('.pg-projects-menu__pop');
		const setMenu = (open) => {
			if (!toggle || !pop) return;
			pop.hidden = !open;
			toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
			menu.classList.toggle('is-open', open);
		};
		if (toggle) {
			toggle.addEventListener('click', (event) => {
				event.stopPropagation();
				setMenu(pop.hidden);
			});
		}
		document.addEventListener('click', (event) => {
			if (menu && !menu.contains(event.target)) setMenu(false);
		});

		// Panel de control
		const panel = document.getElementById('pg-panel');
		const backdrop = document.querySelector('.pg-panel-backdrop');
		const opener = dock.querySelector('[data-pg-panel-open]');
		const setPanel = (open) => {
			if (!panel) return;
			panel.hidden = !open;
			if (backdrop) backdrop.hidden = !open;
			document.documentElement.classList.toggle('pg-panel-open', open);
			if (opener) opener.setAttribute('aria-expanded', open ? 'true' : 'false');
			if (open) {
				setMenu(false);
				const first = panel.querySelector('.pg-panel__close');
				if (first) first.focus();
			} else if (opener) {
				opener.focus();
			}
		};
		if (opener) opener.addEventListener('click', () => setPanel(panel.hidden));
		document.querySelectorAll('[data-pg-panel-close]').forEach((node) => {
			node.addEventListener('click', () => setPanel(false));
		});

		// Un salto desde el panel lo cierra: si no, en móvil tapa el destino.
		if (panel) {
			panel.addEventListener('click', (event) => {
				const link = event.target.closest('a[href^="#"]');
				if (!link) return;
				if (link.getAttribute('aria-disabled') === 'true') {
					event.preventDefault();
					return;
				}
				setPanel(false);
			});
		}

		document.addEventListener('keydown', (event) => {
			if (event.key !== 'Escape') return;
			if (panel && !panel.hidden) setPanel(false);
			else setMenu(false);
		});

		syncJumps();
	}

	async function boot() {
		initNav();
		const root = document.querySelector('[data-pg-report]');
		if (!root) return;

		const postId = Number(root.dataset.pgReport || CFG.postId);
		const reportPath = SHARED
			? '/shared/' + encodeURIComponent(CFG.shareToken) + '/report'
			: '/projects/' + postId + '/report';
		root.innerHTML = '<div class="pg-loading">' + (T.loading || 'Cargando…') + '</div>';

		// Vuelta de Stripe. El webhook desbloquea el informe en segundo plano,
		// así que al aterrizar aquí la v2 puede no existir todavía: el motor
		// devuelve la v1 (básica), que es un 200 perfectamente válido.
		//
		// Sin esto, el cliente que ACABA DE PAGAR ve su informe con las
		// secciones bloqueadas y el botón de comprar. Es el peor momento
		// posible para un fallo, y no lo detecta ningún reintento por error
		// porque no hay error: hay una respuesta correcta y antigua.
		const justPaid = !SHARED && /[?&]pg_pago=ok\b/.test(window.location.search);
		const waitUntil = Date.now() + 180000;   // 3 min: si el webhook no ha
		                                         // llegado, algo va mal de verdad

		let delay = 2000;
		const attempt = async () => {
			try {
				const payload = await api(reportPath);

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
				// textContent: en la página del invitado el mensaje lo decide
				// el servidor, pero no se interpreta como HTML en ningún caso.
				root.innerHTML = '';
				root.appendChild(el('div', 'pg-error', error.message || T.error));
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
