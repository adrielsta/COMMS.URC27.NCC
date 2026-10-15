/** Browser controller appended to the generated static geometry. */
function mount(container, {onSelect} = {}) {
  if (!(container instanceof Element)) throw new TypeError('RoverAnatomy.mount requires an element');
  container.classList.add('rover-anatomy', 'iso');
  container.innerHTML = DATA.svg;
  const byId = Object.fromEntries(DATA.components.map(item => [item.id,item]));
  const parts = [...container.querySelectorAll('[data-component]')];
  const hotspots = [...container.querySelectorAll('[data-hit]')];
  const statuses = Object.fromEntries(DATA.components.map(item => [item.id,'unknown']));
  let selected = null, layer = 'all';
  // SVG image semantics would hide the interactive descendants from assistive tech.
  const svg = container.querySelector('svg');
  svg.setAttribute('role','group');
  svg.setAttribute('aria-label','Rover components. Arrow keys move between components; Enter or Space selects.');
  function select(id, notify = false) {
    if (!byId[id]) return;
    selected = id;
    container.dataset.selectedComponent = id;
    for (const part of parts) part.toggleAttribute('data-selected',part.dataset.component===id);
    for (const point of hotspots) {
      const active=point.dataset.hit===id;
      point.setAttribute('aria-pressed',String(active));
      point.setAttribute('tabindex',active?'0':'-1');
    }
    if (notify && typeof onSelect === 'function') onSelect(id);
  }
  function update(next = {}) {
    for (const item of DATA.components) {
      const data=next?.[item.id];
      let status=typeof data==='string'?data:data?.status;
      if(status==='critical') status='fault';
      if(!Object.hasOwn(DATA.symbols,status)) status='unknown';
      statuses[item.id]=status;
    }
    for(const part of parts) {
      const id=part.dataset.component;
      if(!id) continue;
      part.dataset.status=statuses[id];
      if(part.dataset.hit) {
        const label=`${byId[id].label}: ${statuses[id]}`;
        part.setAttribute('aria-label',label);
        part.querySelector('title').textContent=label;
        part.querySelector('.ra-status-symbol').textContent=DATA.symbols[statuses[id]];
      }
    }
  }
  function setLayer(value) {
    layer=['all','power','drive','avionics','payload'].includes(value)?value:'all';
    container.dataset.layer=layer;
    for(const part of parts) part.toggleAttribute('data-muted',layer!=='all' && part.dataset.layer!==layer && part.dataset.layer!=='structure');
  }
  function click(event) {
    const part=event.target.closest('[data-component]');
    if(part && byId[part.dataset.component]) select(part.dataset.component,true);
  }
  function keydown(event) {
    const point=event.target.closest('[data-hit]');
    if(!point || event.altKey || event.ctrlKey || event.metaKey) return;
    let index=hotspots.indexOf(point);
    if(['ArrowRight','ArrowDown'].includes(event.key)) index=(index+1)%hotspots.length;
    else if(['ArrowLeft','ArrowUp'].includes(event.key)) index=(index+hotspots.length-1)%hotspots.length;
    else if(event.key==='Home') index=0;
    else if(event.key==='End') index=hotspots.length-1;
    else if(event.key==='Enter' || event.key===' ') {event.preventDefault();select(point.dataset.hit,true);return;}
    else return;
    event.preventDefault();
    select(hotspots[index].dataset.hit,true);
    hotspots[index].focus({preventScroll:true});
  }
  container.addEventListener('click',click);
  container.addEventListener('keydown',keydown);
  update();setLayer('all');
  return {update,select,setLayer,destroy(){container.removeEventListener('click',click);container.removeEventListener('keydown',keydown);container.replaceChildren();}};
}
window.RoverAnatomy=Object.freeze({mount,components:Object.freeze(DATA.components.map(item=>Object.freeze({...item}))),solidCount:DATA.solidCount});
