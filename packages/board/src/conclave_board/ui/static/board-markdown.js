// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Laszlo Pinter
//
// board-markdown.js — Markdown fuer die Board-Seite: marked erzeugt HTML, DOMPurify filtert es.
// Der Teil ab "Markdown" ist eine Kopie aus utils.js von Conclave Personal; ein Test prueft, dass
// beide gleich bleiben (gleiche Allowlists, gleiche Hooks).

// Maskiert fuer HTML-Text und Attributwerte (& < > " ').
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

// ── Markdown ──────────────────────────────────────────────────────────────
// Modellausgaben sind nicht vertrauenswuerdig: marked erzeugt HTML, DOMPurify
// filtert es. Ohne DOMPurify wird nie HTML ausgegeben, nur escapter Text.
const MARKDOWN_ALLOWED_TAGS=['a','b','blockquote','br','code','del','div','em','h1','h2','h3','h4','h5','h6',
  'hr','i','input','li','ol','p','pre','s','span','strong','sub','sup','table','tbody','td','th','thead','tr','ul'];
const MARKDOWN_ALLOWED_ATTR=['align','checked','class','colspan','disabled','href','rowspan','start','title','type'];
// Attribute ohne URL-Bedeutung: sonst prueft DOMPurify sie gegen ALLOWED_URI_REGEXP und entfernt sie
const MARKDOWN_URI_SAFE_ATTR=['align','checked','colspan','disabled','rowspan','start','type'];
const _markdownPurifier=_createMarkdownPurifier();

function _createMarkdownPurifier(){
  if(typeof DOMPurify!=='function') return null;
  const purifier=DOMPurify(window);  // eigene Instanz, damit die Hooks lokal bleiben
  if(!purifier.isSupported) return null;
  // class nur als Sprachangabe an code (Syntaxhervorhebung), sonst liessen sich App-Elemente nachbauen (R5)
  purifier.addHook('uponSanitizeAttribute',(node,data)=>{
    if(data.attrName==='class'&&!(node.tagName==='CODE'&&/^language-[\w+-]+$/.test(data.attrValue))){
      data.keepAttr=false;
    }
  });
  purifier.addHook('afterSanitizeAttributes',node=>{
    if(node.tagName==='A'&&node.hasAttribute('href')){
      const href=node.getAttribute('href');
      // Fragment so bestimmen wie der Browser beim Oeffnen (URL-Parser entfernt u. a. Tabs und
      // Zeilenumbrueche) und so lesen wie der Login (URLSearchParams auf location.hash).
      let fragment='', parsed=true;
      try{fragment=new URL(href,window.location.href).hash.slice(1);}catch{parsed=false;}
      let decoded=fragment;
      try{decoded=decodeURIComponent(fragment);}catch{}
      let hasToken=!parsed;
      try{hasToken=hasToken||new URLSearchParams(fragment).has('token');}catch{hasToken=true;}
      if(hasToken||/token=/i.test(decoded)||/token=/i.test(fragment)){
        node.removeAttribute('href');            // Links duerfen kein Token setzen (R5)
      }else if(href.trim().startsWith('#')){
        node.removeAttribute('target');          // Sprungmarke im selben Tab
      }else{
        node.setAttribute('target','_blank');
        node.setAttribute('rel','noopener noreferrer');
      }
    }
    // GFM-Tasklisten: nur deaktivierte Checkboxen
    if(node.tagName==='INPUT'){
      if(node.getAttribute('type')!=='checkbox'){node.remove();return;}
      node.setAttribute('disabled','');
    }
  });
  return purifier;
}

function sanitizeHtml(html){
  if(!_markdownPurifier) return esc(html);
  return _markdownPurifier.sanitize(html,{
    ALLOWED_TAGS:MARKDOWN_ALLOWED_TAGS,
    ALLOWED_ATTR:MARKDOWN_ALLOWED_ATTR,
    ALLOWED_URI_REGEXP:/^(?:(?:https?|mailto):|#)/i,
    ADD_URI_SAFE_ATTR:MARKDOWN_URI_SAFE_ATTR,
    ALLOW_DATA_ATTR:false,
  });
}

function renderMarkdown(text){
  if(typeof marked==='undefined'||!_markdownPurifier) return esc(text);
  try{return sanitizeHtml(marked.parse(String(text)));}catch{return esc(text);}
}
