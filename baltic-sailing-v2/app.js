const parts={"captain-sea":2,"cliff-adventure":2,"hero-yacht":1,"crew":1,"interior":1,"town-view":1};
const cache={};
async function imageData(name){if(cache[name])return cache[name];let s="";for(let i=0;i<parts[name];i++)s+=await(await fetch(`assets/${name}.${i}.b64`)).text();return cache[name]="data:image/webp;base64,"+s.trim()}
async function loadImages(){for(const name of Object.keys(parts)){try{const src=await imageData(name);document.querySelectorAll(`[data-photo="${name}"]`).forEach(x=>{x.src=src;x.onload=()=>x.className="loaded"})}catch(e){console.error(name,e)}}}
async function setLang(lang){const d=await(await fetch(`lang-${lang}.json`)).json();document.documentElement.lang=lang;document.documentElement.dir=lang==="he"?"rtl":"ltr";document.querySelectorAll("[data-t]").forEach(el=>el.textContent=d[el.dataset.t]||"");document.querySelectorAll("[data-lang]").forEach(b=>b.classList.toggle("active",b.dataset.lang===lang));localStorage.setItem("sailLang",lang)}
document.querySelectorAll("[data-lang]").forEach(b=>b.onclick=()=>setLang(b.dataset.lang));
setLang(localStorage.getItem("sailLang")||"he");loadImages();