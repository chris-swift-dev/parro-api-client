// Swagger UI configuration for the GitHub Pages site (copied over the stock initializer).
window.onload = function () {
  window.ui = SwaggerUIBundle({
    url: "parro.openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    docExpansion: "list",
    defaultModelsExpandDepth: 0,
    displayRequestDuration: true,
    validatorUrl: null, // don't send the spec to the external swagger.io validator badge
    presets: [SwaggerUIBundle.presets.apis],
    layout: "BaseLayout"
  });
};
