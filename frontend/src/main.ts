import "./style.css";

const form = document.querySelector<HTMLFormElement>("#quote-form");
const message = document.querySelector<HTMLParagraphElement>("#form-message");
const results = document.querySelector<HTMLElement>(".results-section");

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

if (!form || !message || !results) {
  throw new Error("No se encontraron los elementos del formulario.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const origin = document.querySelector<HTMLInputElement>("#origin")?.value.trim();
  const destination = document.querySelector<HTMLInputElement>("#destination")?.value.trim();
  const weightValue = document.querySelector<HTMLInputElement>("#weight")?.value;
  const email = document.querySelector<HTMLInputElement>("#email")?.value.trim();

  const weight = Number(weightValue);

  if (!origin || !destination || !email || !weightValue || !Number.isFinite(weight) || weight <= 0) {
    message.textContent = "Completa todos los campos con datos válidos.";
    return;
  }

  message.textContent = "Procesando tu solicitud...";
  results.innerHTML = "";

  try {
    // 1. Guardar la solicitud en PostgreSQL mediante el backend.
    const saveResponse = await fetch(`${API_URL}/solicitudes-cotizacion`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email,
        codigo_postal1: origin,
        codigo_postal2: destination,
        peso: weight,
      }),
    });

    if (!saveResponse.ok) {
      const error = await saveResponse.json().catch(() => null);
      throw new Error(error?.detail || "No se pudo guardar la solicitud.");
    }

    // 2. Calcular la distancia y obtener la zona.
    const distanceResponse = await fetch(`${API_URL}/distance`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        codigo_postal1: origin,
        codigo_postal2: destination,
      }),
    });

    if (!distanceResponse.ok) {
      const error = await distanceResponse.json().catch(() => null);
      throw new Error(error?.detail || "No se pudo calcular la distancia.");
    }

    const distanceData = await distanceResponse.json();

    // 3. Consultar las tarifas disponibles para esa zona y peso.
    const quoteResponse = await fetch(`${API_URL}/cotizaciones`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        zona: distanceData.zona,
        peso: weight,
      }),
    });

    if (!quoteResponse.ok) {
      const error = await quoteResponse.json().catch(() => null);
      throw new Error(error?.detail || "No se pudieron consultar las tarifas.");
    }

    const quoteData = await quoteResponse.json();

    // 4. Mostrar las opciones sin modificar los estilos CSS.
    if (!quoteData.opciones || quoteData.opciones.length === 0) {
      results.textContent = "No encontramos tarifas para los datos ingresados.";
    } else {
      const title = document.createElement("h2");
      title.textContent = "Opciones de envío";
      results.appendChild(title);

      const list = document.createElement("div");


      for (const option of quoteData.opciones) {
        const item = document.createElement("article");

        // Función para mostrar un texto alternativo cuando falte un dato.
        const mostrarDato = (valor: unknown): string => {
          if (valor == null) {
            return "Dato no disponible";
          }

          const texto = String(valor).trim();

          if (
            texto === "" ||
            texto.toLowerCase() === "null" ||
            texto.toLowerCase() === "undefined"
          ) {
            return "Dato no disponible";
          }

          return texto;
        };

        const carrier = document.createElement("h3");
        carrier.textContent = mostrarDato(option.paqueteria);

        const price = document.createElement("p");
        const precio = mostrarDato(option.precio);

        price.textContent =
          precio === "Dato no disponible"
            ? `Precio: ${precio}`
            : `Precio: $${Number(option.precio).toFixed(2)}`;

        const zone = document.createElement("p");
        zone.textContent = `Zona: ${mostrarDato(option.zona)}`;

        const minWeight = document.createElement("p");
        minWeight.textContent = `Peso mínimo: ${mostrarDato(option.peso_min)} kg`;

        const maxWeight = document.createElement("p");
        maxWeight.textContent = `Peso máximo: ${mostrarDato(option.peso_max)} kg`;

        const delivery = document.createElement("p");
        delivery.textContent = `Días de entrega: ${mostrarDato(option.dias_entrega)}`;

        const validity = document.createElement("p");
        validity.textContent = `Vigencia desde: ${mostrarDato(option.vigencia_desde)}`;

        item.append(
          carrier,
          price,
          zone,
          minWeight,
          maxWeight,
          delivery,
          validity
        );

        list.appendChild(item);
      }

      results.appendChild(list);
    }

    message.textContent = "Solicitud guardada. Aquí están tus opciones de envío.";
  } catch (error) {
    message.textContent =
      error instanceof Error
        ? error.message
        : "Ocurrió un error al procesar tu solicitud.";
  }
}); 