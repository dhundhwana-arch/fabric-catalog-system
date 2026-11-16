const API = "/api/v1";
const $ = (id) => document.getElementById(id);
let page = 1, pageSize = 20, totalPages = 1;

function adminKey(){ return localStorage.getItem("admin_key") || ""; }
function authHeaders(){ return { "Authorization": "Bearer " + adminKey(), "Content-Type": "application/json" }; }
async function api(path, opts = {}){
  const res = await fetch(API + path, opts);
  if(!res.ok){ const t = await res.text(); throw new Error(res.status + " " + t); }
  return res.json();
}

// Tabs
$("tab-catalogue").onclick = () => { $("view-catalogue").hidden = false; $("view-admin").hidden = true; $("tab-catalogue").classList.add("active"); $("tab-admin").classList.remove("active"); };
$("tab-admin").onclick = () => { $("view-admin").hidden = false; $("view-catalogue").hidden = true; $("tab-admin").classList.add("active"); $("tab-catalogue").classList.remove("active"); };

// Categories in filter + admin selects
async function loadCategories(){
  const cats = await api("/categories");
  const opts = cats.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  $("f-category").innerHTML = `<option value="">All categories</option>` + opts;
  $("a-fab-cat").innerHTML = `<option value="">No category</option>` + opts;
}

function filters(){
  const p = new URLSearchParams({ page, page_size: pageSize });
  const s = $("f-search").value.trim(); if(s) p.set("search", s);
  const c = $("f-category").value; if(c) p.set("category_id", c);
  const col = $("f-colour").value.trim(); if(col) p.set("colour", col);
  const av = $("f-availability").value; if(av) p.set("availability", av);
  const mn = $("f-min").value; if(mn) p.set("min_price", mn);
  const mx = $("f-max").value; if(mx) p.set("max_price", mx);
  return p.toString();
}

async function loadCatalogue(){
  const data = await api("/fabrics?" + filters());
  totalPages = data.pages;
  $("pg-info").textContent = `Page ${data.page} of ${data.pages} · ${data.total} fabrics`;
  const grid = $("catalogue-grid");
  if(!data.items.length){ grid.innerHTML = `<p>No fabrics match. New stock is added only when verified.</p>`; return; }
  grid.innerHTML = "";
  for(const f of data.items){
    const detail = await api(`/fabrics/${f.id}`);
    const el = document.createElement("div");
    el.className = "card";
    const img = detail.images.find(i => i.is_primary) || detail.images[0];
    const swatches = detail.variants.map(v =>
      `<span title="${v.colour_name}"><span class="swatch" style="background:${v.colour_hex}"></span>${v.colour_name} · ${v.availability_status}${v.customer_price != null ? " · ₹" + v.customer_price + "/" + v.unit : ""}</span>`
    ).join("<br>");
    el.innerHTML = `
      ${img ? `<img src="${img.image_url}" alt="${img.image_description || f.fabric_name}" style="width:100%;border-radius:8px">` : `<div style="height:120px;background:#f3f4f6;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#9ca3af">No photo yet</div>`}
      <h3>${f.fabric_name}</h3>
      <p class="meta">${f.fabric_id} · ${f.fabric_type || "—"} · ${f.composition || "composition not verified"}</p>
      <p class="meta">Sourcing: ${f.sourcing_method.replace("_"," ")}</p>
      <p>${swatches || "No colour variants listed."}</p>
      <button data-id="${f.id}">View details</button>`;
    el.querySelector("button").onclick = () => openDetail(f.id);
    grid.appendChild(el);
  }
}

async function openDetail(id){
  const d = await api(`/fabrics/${id}`);
  $("modal-body").innerHTML = `
    <h2>${d.fabric_name} <small>(${d.fabric_id})</small></h2>
    <p>${d.description || ""}</p>
    <p class="meta">Type: ${d.fabric_type || "—"} · Composition: ${d.composition || "not verified"} · Sourcing: ${d.sourcing_method}</p>
    <h3>Colours</h3>
    ${d.variants.map(v => `<p><span class="swatch" style="background:${v.colour_hex}"></span><b>${v.colour_name}</b> (${v.variant_id}) — <span class="badge ${v.availability_status}">${v.availability_status}</span> ${v.customer_price != null ? `<span class="price">₹${v.customer_price} / ${v.unit}</span>` : "price on request"}</p>`).join("") || "<p>No variants.</p>"}
    <h3>Photos</h3>
    ${d.images.map(i => `<img src="${i.image_url}" alt="${i.image_description || ""}"><p class="meta">${i.image_type} — ${i.image_description || ""}</p>`).join("") || "<p>No photos yet.</p>"}`;
  $("modal").hidden = false;
}
$("modal-close").onclick = () => $("modal").hidden = true;
$("modal").onclick = (e) => { if(e.target === $("modal")) $("modal").hidden = true; };

$("f-apply").onclick = () => { page = 1; loadCatalogue(); };
$("f-clear").onclick = () => { ["f-search","f-colour","f-min","f-max"].forEach(i => $(i).value = ""); $("f-category").value = ""; $("f-availability").value = ""; page = 1; loadCatalogue(); };
$("pg-prev").onclick = () => { if(page > 1){ page--; loadCatalogue(); } };
$("pg-next").onclick = () => { if(page < totalPages){ page++; loadCatalogue(); } };

// Admin
$("admin-save").onclick = () => { localStorage.setItem("admin_key", $("admin-key").value.trim()); $("admin-status").textContent = "saved"; };
$("admin-key").value = adminKey();
function msg(t){ $("admin-msg").textContent = t; }
async function adminPost(path, body){ const r = await fetch(API + path, { method:"POST", headers: authHeaders(), body: JSON.stringify(body) }); if(!r.ok) throw new Error(r.status + " " + await r.text()); return r.json(); }

$("a-cat-add").onclick = async () => { try{ await adminPost("/categories", { name: $("a-cat-name").value }); msg("Category added"); loadCategories(); }catch(e){ msg("Error: " + e.message); } };
$("a-fab-add").onclick = async () => { try{ const cat = $("a-fab-cat").value; const r = await adminPost("/fabrics", { fabric_name: $("a-fab-name").value, category_id: cat ? +cat : null, fabric_type: $("a-fab-type").value || null, sourcing_method: $("a-fab-sourcing").value }); msg("Fabric created: " + r.fabric_id); loadCatalogue(); }catch(e){ msg("Error: " + e.message); } };
$("a-var-add").onclick = async () => { try{ const r = await adminPost("/variants", { fabric_id: +$("a-var-fabric").value, colour_name: $("a-var-colour").value, colour_hex: $("a-var-hex").value, customer_price: $("a-var-price").value ? +$("a-var-price").value : null, availability_status: $("a-var-avail").value }); msg("Variant created: " + r.variant_id); loadCatalogue(); }catch(e){ msg("Error: " + e.message); } };
$("a-img-add").onclick = async () => {
  try{
    const fd = new FormData();
    fd.append("file", $("a-img-file").files[0]);
    fd.append("fabric_id", $("a-img-fabric").value);
    fd.append("image_type", $("a-img-type").value);
    const r = await fetch(API + "/images/upload", { method:"POST", headers: { "Authorization": "Bearer " + adminKey() }, body: fd });
    if(!r.ok) throw new Error(r.status + " " + await r.text());
    msg("Photo uploaded"); loadCatalogue();
  }catch(e){ msg("Error: " + e.message); }
};
$("a-inv-save").onclick = async () => { try{ const r = await fetch(API + "/inventory/" + $("a-inv-variant").value, { method:"PUT", headers: authHeaders(), body: JSON.stringify({ stock_quantity: +$("a-inv-stock").value, reserved_quantity: +($("a-inv-reserved").value || 0) }) }); if(!r.ok) throw new Error(r.status + " " + await r.text()); msg("Stock saved"); }catch(e){ msg("Error: " + e.message); } };
$("a-export-json").onclick = () => location.href = API + "/export?format=json";
$("a-export-csv").onclick = () => location.href = API + "/export?format=csv";

loadCategories().then(loadCatalogue);
