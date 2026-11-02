/** Homepage UI stays useful even when WebGL is unavailable. */
export function initObservatory() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const motionButton = document.querySelector<HTMLButtonElement>('#motion-toggle')!;
  let paused = reduced.matches;
  const setMotion = () => {
    motionButton.setAttribute('aria-pressed', String(paused));
    motionButton.setAttribute('aria-label', paused ? 'Resume scene motion' : 'Pause scene motion');
    window.dispatchEvent(new CustomEvent('prince:motion', { detail: paused }));
  };
  motionButton.addEventListener('click', () => { paused = !paused; setMotion(); });
  reduced.addEventListener('change', () => { paused = reduced.matches; setMotion(); });
  setMotion();

  const dialogs = ['navigation', 'about-scene'].map(id => document.getElementById(id) as HTMLDialogElement);
  const launchers = ['open-menu', 'scene-info'];
  dialogs.forEach((dialog, index) => {
    const launcher = document.getElementById(launchers[index])!;
    launcher.addEventListener('click', () => {
      dialog.showModal();
      document.body.style.overflow = 'hidden';
      window.dispatchEvent(new CustomEvent('prince:dialog', { detail: true }));
    });
    dialog.querySelector('.close-dialog')?.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      const rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
      document.body.style.overflow = '';
      window.dispatchEvent(new CustomEvent('prince:dialog', { detail: false }));
      launcher.focus();
    });
  });

  const sections = [...document.querySelectorAll<HTMLElement>('[data-chapter]')];
  const navLinks = [...document.querySelectorAll<HTMLAnchorElement>('.chapter-nav>a')];
  const next = document.getElementById('next-chapter') as HTMLAnchorElement;
  let current = -1;
  let scheduled = false;
  function updateChapter() {
    scheduled = false;
    let active = 0;
    sections.forEach((section, i) => { if (section.getBoundingClientRect().top < innerHeight * .45) active = i; });
    if (active === current) return;
    current = active;
    navLinks.forEach((link, i) => i === active ? link.setAttribute('aria-current', 'step') : link.removeAttribute('aria-current'));
    document.getElementById('chapter-number')!.textContent = `0${active + 1} / 05`;
    document.getElementById('journey-label')!.textContent = active === 4 ? 'Back to the start' : 'Scroll to explore';
    next.href = `#${sections[(active + 1) % sections.length].id}`;
  }
  addEventListener('scroll', () => { if (!scheduled) { scheduled = true; requestAnimationFrame(updateChapter); } }, { passive: true });
  updateChapter();

  const view = document.getElementById('specimen-view') as HTMLButtonElement;
  view.addEventListener('click', () => {
    const trace = view.getAttribute('aria-pressed') !== 'true';
    view.setAttribute('aria-pressed', String(trace));
    view.setAttribute('aria-label', trace ? 'Show sculptural protein beads' : 'Show protein backbone trace');
    view.innerHTML = trace ? 'View sculpture <span>◉</span>' : 'View trace <span>◌</span>';
    window.dispatchEvent(new CustomEvent('prince:trace', { detail: trace }));
  });

  import('./world').then(({ createWorld }) => {
    const cleanup = createWorld(document.getElementById('world')!, sections, paused);
    addEventListener('pagehide', event => { if (!event.persisted) cleanup(); }, { once: true });
  }).catch(error => {
    console.warn('Prince: the optional 3D scene could not start.', error);
    view.hidden = true;
    motionButton.hidden = true;
    document.getElementById('world')!.classList.add('is-unavailable');
  });
}
