import "./style.css";

const form = document.querySelector<HTMLFormElement>("#quote-form");
const message = document.querySelector<HTMLParagraphElement>("#form-message");

// Dirección del backend FastAPI
const API_URL = "http://localhost:8000";

form?.addEventListener("submit", async (event: SubmitEvent) => {
  event.preventDefault();

  if (!form.reportValidity()) {
    return;
  }

  const originInput =
    document.querySelector<HTMLInputElement>("#origin");
  const destinationInput =
    document.querySelector<HTMLInputElement>("#destination");

  if (!originInput || !destinationInput || !message) {
    return;
  }

  const codigo_postal1 = originInput.value.trim();
  const codigo_postal2 = destinationInput.value.trim();

  message.textContent = "Calculando distancia...";
  message.className = "form-message visible info";

  try {
    const response = await fetch(`${API_URL}/distance`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        codigo_postal1,
        codigo_postal2,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "No fue posible calcular la distancia."
      );
    }

    message.textContent =
      `Distancia: ${data.distancia_km} km. ` +
      `Origen: ${data.origen.localidad}, ${data.origen.estado}. ` +
      `Destino: ${data.destino.localidad}, ${data.destino.estado}.`;

    message.className = "form-message visible success";
  } catch (error) {
    message.textContent =
      error instanceof Error
        ? error.message
        : "No fue posible conectar con el servidor.";

    message.className = "form-message visible error";
  }
});