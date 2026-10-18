/**
 * PowerGIS · compartir un proyecto por correo.
 *
 * Abre el diálogo cualquier elemento con `data-pg-share-open` (su valor es el
 * id del proyecto; si va vacío se usa `PowerGISConfig.postId`). El clic se
 * escucha en `document`, así que el botón puede vivir en la cabecera, en el
 * panel de control o en un menú que se pinte más tarde: no hay que volver a
 * enlazar nada.
 *
 * Rutas (saas/v1, con nonce):
 *   GET    /projects/{id}/shares        enlaces vigentes
 *   POST   /projects/{id}/shares        { emails: [], duration }
 *   DELETE /projects/{id}/shares/{sid}  retirar un enlace
 *
 * @package PowerGIS
 */

(function () {
	'use strict';

	const CFG = window.PowerGISConfig || {};

	// El orden es el del desplegable; `siempre` va marcado por defecto.
	const DURATIONS = [
		['siempre', 'Siempre'],
		['1h', '1 hora'],
		['3h', '3 horas'],
		['24h', '24 horas'],
		['1m', '1 mes'],
		['1a', '1 año'],
	];

	const el = (tag, cls, text) => {
		const node = document.createElement(tag);
		if (cls) node.className = cls;
		if (text !== undefined && text !== null) node.textContent = String(text);
		return node;
	};

	const api = async (path, options) => {
		const response = await fetch(CFG.restUrl + path, Object.assign({
			headers: { 'X-WP-Nonce': CFG.nonce, 'Content-Type': 'application/json' },
			credentials: 'same-origin',
		}, options || {}));
		const body = await response.json().catch(() => ({}));
		if (!response.ok) {
			throw new Error(body.message || response.statusText);
		}
		return body;
	};

	const when = (iso) => new Date(iso).toLocaleString('es-ES', {
		day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
	});

	let dialog = null;

	function build() {
		const box = el('dialog', 'pg-share');
		box.setAttribute('aria-labelledby', 'pg-share-title');

		const head = el('div', 'pg-share__head');
		const title = el('h2', null, 'Compartir proyecto');
		title.id = 'pg-share-title';
		const close = el('button', 'pg-share__close', '×');
		close.type = 'button';
		close.setAttribute('aria-label', 'Cerrar');
		close.addEventListener('click', () => box.close());
		head.append(title, close);

		const form = el('form', 'pg-share__form');
		form.method = 'dialog';

		const emailsLabel = el('label', 'pg-share__label', 'Correos de las personas invitadas');
		const emails = el('textarea', 'pg-share__emails');
		emails.name = 'emails';
		emails.rows = 3;
		emails.required = true;
		emails.placeholder = 'ana@empresa.es, luis@empresa.es';
		emailsLabel.appendChild(emails);

		const durationLabel = el('label', 'pg-share__label', 'Pueden verlo durante');
		const duration = el('select', 'pg-share__duration');
		duration.name = 'duration';
		DURATIONS.forEach(([value, text]) => {
			const option = el('option', null, text);
			option.value = value;
			duration.appendChild(option);
		});
		duration.value = 'siempre';
		durationLabel.appendChild(duration);

		const note = el('p', 'pg-share__note pg-muted',
			'Cada persona recibe su propio enlace por correo. Solo verá este informe: '
			+ 'ni tus otros proyectos ni los datos de tu cuenta.');

		const submit = el('button', 'pg-cta', 'Enviar invitación');
		submit.type = 'submit';

		const status = el('p', 'pg-share__status');
		status.setAttribute('role', 'status');
		status.hidden = true;

		form.append(emailsLabel, durationLabel, note, submit, status);

		const listTitle = el('h3', 'pg-share__subtitle', 'Con acceso ahora');
		const list = el('ul', 'pg-share__list');

		box.append(head, form, listTitle, list);
		document.body.appendChild(box);

		// Cerrar al pulsar fuera del cuadro.
		box.addEventListener('click', (event) => {
			if (event.target === box) box.close();
		});

		const say = (text, isError) => {
			status.textContent = text;
			status.className = 'pg-share__status' + (isError ? ' pg-share__status--error' : '');
			status.hidden = false;
		};

		form.addEventListener('submit', async (event) => {
			event.preventDefault();
			submit.disabled = true;
			say('Enviando…');
			try {
				const result = await api('/projects/' + box.dataset.postId + '/shares', {
					method: 'POST',
					body: JSON.stringify({ emails: [emails.value], duration: duration.value }),
				});
				let text = result.sent === 1 ? 'Invitación enviada.' : 'Invitaciones enviadas: ' + result.sent + '.';
				if (result.failed && result.failed.length) {
					text += ' No se pudo enviar a: ' + result.failed.join(', ') + '.';
				}
				say(text, Boolean(result.failed && result.failed.length));
				emails.value = '';
				duration.value = 'siempre';
				drawList(list, box.dataset.postId, result.shares || []);
			} catch (error) {
				say(error.message || 'No se pudo compartir.', true);
			} finally {
				submit.disabled = false;
			}
		});

		box._refs = { list, status, emails };
		return box;
	}

	function drawList(list, postId, shares) {
		list.innerHTML = '';
		if (!shares.length) {
			list.appendChild(el('li', 'pg-share__empty pg-muted', 'Todavía no lo has compartido con nadie.'));
			return;
		}
		shares.forEach((share) => {
			const item = el('li', 'pg-share__item');
			const info = el('div');
			info.appendChild(el('span', 'pg-share__email', share.email));
			const detail = share.expires_at ? 'Hasta el ' + when(share.expires_at) : 'Sin caducidad';
			const seen = share.views ? ' · visto ' + share.views + (share.views === 1 ? ' vez' : ' veces') : ' · sin abrir';
			info.appendChild(el('span', 'pg-share__meta pg-muted', detail + seen));

			const revoke = el('button', 'pg-btn pg-share__revoke', 'Retirar acceso');
			revoke.type = 'button';
			revoke.addEventListener('click', async () => {
				revoke.disabled = true;
				try {
					await api('/projects/' + postId + '/shares/' + share.id, { method: 'DELETE' });
					item.remove();
					if (!list.children.length) drawList(list, postId, []);
				} catch (error) {
					revoke.disabled = false;
					revoke.textContent = error.message || 'No se pudo retirar';
				}
			});
			item.append(info, revoke);
			list.appendChild(item);
		});
	}

	async function open(postId) {
		dialog = dialog || build();
		dialog.dataset.postId = String(postId);
		dialog._refs.status.hidden = true;
		dialog._refs.list.innerHTML = '';
		dialog._refs.list.appendChild(el('li', 'pg-muted', 'Cargando…'));
		if (typeof dialog.showModal === 'function') {
			dialog.showModal();
		} else {
			dialog.setAttribute('open', '');
		}
		dialog._refs.emails.focus();
		try {
			drawList(dialog._refs.list, postId, await api('/projects/' + postId + '/shares'));
		} catch (error) {
			dialog._refs.list.innerHTML = '';
			dialog._refs.list.appendChild(el('li', 'pg-share__status--error', error.message));
		}
	}

	document.addEventListener('click', (event) => {
		const trigger = event.target.closest && event.target.closest('[data-pg-share-open]');
		if (!trigger) return;
		event.preventDefault();
		const postId = Number(trigger.getAttribute('data-pg-share-open')) || Number(CFG.postId);
		if (postId) open(postId);
	});

	// Para quien prefiera abrirlo desde su propio código.
	window.PowerGISShare = { open };
})();
