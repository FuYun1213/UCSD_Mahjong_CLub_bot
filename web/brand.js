/* One formal club name for both languages and browser metadata. */
window.MahjongBrand = Object.freeze({name: "DORA Mahjong Club at UC San Diego"});
document.title = window.MahjongBrand.name;
for (const node of document.querySelectorAll('[data-club-brand]')) node.setAttribute("content", window.MahjongBrand.name);
