// static/js/swagger-init.js — Swagger UI fuer /api-docs (ohne Inline-Skript, wegen CSP)
window.addEventListener('DOMContentLoaded',()=>{
  SwaggerUIBundle({url:'/static/openapi.json',dom_id:'#swagger-ui',deepLinking:true,validatorUrl:null});
});
