/* Shared by the browser and static page build; keep the legal copy in one place. */
(() => {
 const name = "DORA Mahjong Club at UC San Diego";
 const brand = Object.freeze({
  name,
  disclaimer: name + " is a registered student organization at the University of California, San Diego, but is not part of the University itself. The University does not assume legal liability for the actions of the organization."
 });
 if (typeof module === "object" && module.exports) module.exports = brand;
 if (typeof window !== "undefined") {
  window.MahjongBrand = brand;
  document.title = brand.name;
  for (const node of document.querySelectorAll('[data-club-brand]')) node.setAttribute("content", brand.name);
 }
})();
