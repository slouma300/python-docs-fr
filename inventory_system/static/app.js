const stockTable = document.querySelector("#stockTable");
const movementTable = document.querySelector("#movementTable");
const stockCount = document.querySelector("#stockCount");
const message = document.querySelector("#scanResult");
const globalBarcode = document.querySelector("#globalBarcode");
const cameraPreview = document.querySelector("#cameraPreview");

let cameraStream = null;
let cameraTimer = null;

function formToPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function setMessage(text, type = "") {
  message.textContent = text;
  message.className = `message ${type}`.trim();
}

function copyBarcodeToForms(barcode) {
  document
    .querySelectorAll('input[name="barcode"]')
    .forEach((input) => {
      input.value = barcode;
    });
}

async function submitMovement(form, endpoint, successText) {
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const payload = formToPayload(form);
    await api(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setMessage(successText, "success");
    await refreshData();
    form.reset();
    form.querySelector('input[name="quantity"]').value = 1;
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function lookupBarcode(barcode) {
  const cleanBarcode = barcode.trim();
  if (!cleanBarcode) {
    setMessage("Scan or type a barcode first.", "error");
    return;
  }

  try {
    const result = await api(`/api/scan?barcode=${encodeURIComponent(cleanBarcode)}`);
    copyBarcodeToForms(cleanBarcode);
    if (!result.found) {
      setMessage(
        `Barcode ${cleanBarcode} is new. Use Stock in to create it.`,
        "success",
      );
      return;
    }

    const locations = result.locations
      .map((item) => `${item.location}: ${item.quantity}`)
      .join(", ");
    setMessage(
      `${result.product.name} has ${result.total_quantity} units. ${locations || "No stock by location."}`,
      "success",
    );
  } catch (error) {
    setMessage(error.message, "error");
  }
}

function renderRows(tableBody, rows, columns) {
  tableBody.textContent = "";
  if (rows.length === 0) {
    const emptyRow = document.querySelector("#emptyRowTemplate").content.cloneNode(true);
    emptyRow.querySelector("td").colSpan = columns.length;
    tableBody.append(emptyRow);
    return;
  }

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      td.textContent = row[column.key] || "";
      if (column.number) {
        td.classList.add("number");
      }
      tr.append(td);
    });
    tableBody.append(tr);
  });
}

async function refreshData() {
  const [stockResponse, movementResponse] = await Promise.all([
    api("/api/stock"),
    api("/api/movements?limit=50"),
  ]);

  renderRows(stockTable, stockResponse.stock, [
    { key: "barcode" },
    { key: "product_name" },
    { key: "location" },
    { key: "quantity", number: true },
  ]);
  stockCount.textContent = `${stockResponse.stock.length} stock rows`;

  renderRows(movementTable, movementResponse.movements, [
    { key: "created_at" },
    { key: "movement_type" },
    { key: "barcode" },
    { key: "product_name" },
    { key: "from_location" },
    { key: "to_location" },
    { key: "quantity", number: true },
    { key: "note" },
  ]);
}

async function stopCamera() {
  if (cameraTimer) {
    clearInterval(cameraTimer);
    cameraTimer = null;
  }
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  cameraPreview.classList.add("hidden");
  document.querySelector("#cameraButton").textContent = "Start camera scan";
}

async function startCameraScan() {
  if (cameraStream) {
    await stopCamera();
    return;
  }

  if (!("BarcodeDetector" in window)) {
    setMessage(
      "Camera scanning is not supported in this browser. Use a hardware scanner or type the barcode.",
      "error",
    );
    return;
  }

  try {
    const detector = new BarcodeDetector({
      formats: ["aztec", "code_128", "code_39", "ean_13", "ean_8", "qr_code", "upc_a", "upc_e"],
    });
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
    });
    cameraPreview.srcObject = cameraStream;
    cameraPreview.classList.remove("hidden");
    await cameraPreview.play();
    document.querySelector("#cameraButton").textContent = "Stop camera scan";
    setMessage("Point the camera at a barcode.", "success");

    cameraTimer = setInterval(async () => {
      try {
        const codes = await detector.detect(cameraPreview);
        if (codes.length > 0) {
          const code = codes[0].rawValue;
          globalBarcode.value = code;
          await stopCamera();
          await lookupBarcode(code);
        }
      } catch (error) {
        await stopCamera();
        setMessage(error.message, "error");
      }
    }, 500);
  } catch (error) {
    await stopCamera();
    setMessage(error.message, "error");
  }
}

document.querySelector("#stockInForm").addEventListener("submit", (event) => {
  event.preventDefault();
  submitMovement(event.currentTarget, "/api/stock-in", "Stock added.");
});

document.querySelector("#stockOutForm").addEventListener("submit", (event) => {
  event.preventDefault();
  submitMovement(event.currentTarget, "/api/stock-out", "Stock removed.");
});

document.querySelector("#transferForm").addEventListener("submit", (event) => {
  event.preventDefault();
  submitMovement(event.currentTarget, "/api/transfer", "Stock transferred.");
});

document.querySelector("#refreshButton").addEventListener("click", refreshData);
document.querySelector("#scanLookupButton").addEventListener("click", () => {
  lookupBarcode(globalBarcode.value);
});
document.querySelector("#cameraButton").addEventListener("click", startCameraScan);
globalBarcode.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    lookupBarcode(globalBarcode.value);
  }
});

refreshData().catch((error) => setMessage(error.message, "error"));
