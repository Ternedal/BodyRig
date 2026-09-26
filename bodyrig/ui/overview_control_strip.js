(() => {
  const $ = (id) => document.getElementById(id);
  function text(id){ return ($(id)?.textContent || "").replace(/\s+/g," ").trim(); }
  function setChip(id,state,active){
    const chip=$(id); if(!chip) return;
    const s=chip.querySelector(".chip-state"); if(s) s.textContent=state||"—";
    chip.classList.toggle("active",Boolean(active));
  }
  function refresh(){
    const pipeline=text("overviewCockpitBadge");
    const revision=text("overviewPersonRevision");
    const twin=text("operator-digital-twin-badge");
    const next=text("overviewCockpitNext");
    const attention=text("overviewCockpitAttention");
    setChip("overviewControlPipeline",pipeline||"Ukendt",/^Komplet$/i.test(pipeline));
    setChip("overviewControlRevision",revision||"Ingen",Boolean(revision&&!/ingen/i.test(revision)));
    setChip("overviewControlTwin",twin||"Ukendt",/^M6 klar$/i.test(twin));
    const node=$("overviewControlNext");
    if(node) node.textContent=attention||next||"Ingen prioriteret handling.";
  }
  $("overviewControlPipeline")?.addEventListener("click",()=>$("overviewCockpitStages")?.scrollIntoView({behavior:"smooth",block:"start"}));
  $("overviewControlRevision")?.addEventListener("click",()=>document.querySelector('.tab[data-tab="history"]')?.click());
  $("overviewControlTwin")?.addEventListener("click",()=>document.querySelector('.tab[data-tab="operations"]')?.click());
  for(const id of ["overviewCockpitBadge","overviewPersonRevision","operator-digital-twin-badge","overviewCockpitNext","overviewCockpitAttention"]){
    const node=$(id);
    if(node) new MutationObserver(refresh).observe(node,{childList:true,characterData:true,subtree:true,attributes:true});
  }
  refresh();
})();