const STORAGE_KEY = "inventory-system-vercel-v1";

function emptyState() {
  return {
    products: [],
    locations: [],
    stockLevels: [],
    movements: [],
    nextIds: {
      product: 1,
      location: 1,
      movement: 1,
    },
  };
}

function loadState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return emptyState();
  }

  try {
    return { ...emptyState(), ...JSON.parse(raw) };
  } catch {
    return emptyState();
  }
}

function saveState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function cleanOptional(value) {
  return value == null ? "" : String(value).trim();
}

function cleanRequired(value, fieldName) {
  const cleaned = cleanOptional(value);
  if (!cleaned) {
    throw new Error(`${fieldName} is required`);
  }
  return cleaned;
}

function cleanQuantity(value) {
  const quantity = Number.parseInt(value, 10);
  if (!Number.isInteger(quantity)) {
    throw new Error("quantity must be a whole number");
  }
  if (quantity <= 0) {
    throw new Error("quantity must be greater than zero");
  }
  return quantity;
}

function nowIso() {
  return new Date().toISOString();
}

export class LocalInventoryStore {
  constructor() {
    this.state = loadState();
  }

  stockIn(payload) {
    const barcode = cleanRequired(payload.barcode, "barcode");
    const locationName = cleanRequired(payload.location, "location");
    const quantity = cleanQuantity(payload.quantity);
    const note = cleanOptional(payload.note);
    const productName = cleanOptional(payload.product_name) || `Item ${barcode}`;

    const product = this.ensureProduct(barcode, productName);
    const location = this.ensureLocation(locationName);
    this.increaseStock(product.id, location.id, quantity);
    const movement = this.recordMovement({
      movement_type: "STOCK_IN",
      product_id: product.id,
      from_location_id: null,
      to_location_id: location.id,
      quantity,
      note,
    });
    this.persist();
    return this.formatMovement(movement);
  }

  stockOut(payload) {
    const barcode = cleanRequired(payload.barcode, "barcode");
    const locationName = cleanRequired(payload.location, "location");
    const quantity = cleanQuantity(payload.quantity);
    const note = cleanOptional(payload.note);

    const product = this.findProductByBarcode(barcode);
    if (!product) {
      throw new Error(`No product found for barcode ${barcode}`);
    }

    const location = this.findLocationByName(locationName);
    if (!location) {
      throw new Error(`Location ${locationName} was not found`);
    }

    this.decreaseStock(product.id, location.id, quantity);
    const movement = this.recordMovement({
      movement_type: "STOCK_OUT",
      product_id: product.id,
      from_location_id: location.id,
      to_location_id: null,
      quantity,
      note,
    });
    this.persist();
    return this.formatMovement(movement);
  }

  transfer(payload) {
    const barcode = cleanRequired(payload.barcode, "barcode");
    const fromLocationName = cleanRequired(payload.from_location, "from_location");
    const toLocationName = cleanRequired(payload.to_location, "to_location");
    if (fromLocationName.toLowerCase() === toLocationName.toLowerCase()) {
      throw new Error("Source and destination locations must differ");
    }
    const quantity = cleanQuantity(payload.quantity);
    const note = cleanOptional(payload.note);

    const product = this.findProductByBarcode(barcode);
    if (!product) {
      throw new Error(`No product found for barcode ${barcode}`);
    }

    const fromLocation = this.findLocationByName(fromLocationName);
    if (!fromLocation) {
      throw new Error(`Location ${fromLocationName} was not found`);
    }

    const toLocation = this.ensureLocation(toLocationName);
    this.decreaseStock(product.id, fromLocation.id, quantity);
    this.increaseStock(product.id, toLocation.id, quantity);
    const movement = this.recordMovement({
      movement_type: "TRANSFER",
      product_id: product.id,
      from_location_id: fromLocation.id,
      to_location_id: toLocation.id,
      quantity,
      note,
    });
    this.persist();
    return this.formatMovement(movement);
  }

  scanBarcode(barcodeValue) {
    const barcode = cleanRequired(barcodeValue, "barcode");
    const product = this.findProductByBarcode(barcode);
    if (!product) {
      return {
        found: false,
        barcode,
        product: null,
        locations: [],
        total_quantity: 0,
      };
    }

    const locations = this.state.stockLevels
      .filter((level) => level.product_id === product.id && level.quantity > 0)
      .map((level) => ({
        location: this.findLocationById(level.location_id)?.name || "",
        quantity: level.quantity,
      }))
      .sort((a, b) => a.location.localeCompare(b.location));
    const total = locations.reduce((sum, item) => sum + item.quantity, 0);

    return {
      found: true,
      barcode,
      product: {
        barcode: product.barcode,
        name: product.name,
        sku: product.sku,
      },
      locations,
      total_quantity: total,
    };
  }

  listStock() {
    return this.state.stockLevels
      .filter((level) => level.quantity > 0)
      .map((level) => {
        const product = this.findProductById(level.product_id);
        const location = this.findLocationById(level.location_id);
        return {
          barcode: product?.barcode || "",
          product_name: product?.name || "",
          location: location?.name || "",
          quantity: level.quantity,
        };
      })
      .sort((a, b) => {
        const productCompare = a.product_name.localeCompare(b.product_name);
        return productCompare || a.location.localeCompare(b.location);
      });
  }

  listMovements(limit = 50) {
    const safeLimit = Math.min(Math.max(Number.parseInt(limit, 10) || 50, 1), 500);
    return [...this.state.movements]
      .sort((a, b) => b.id - a.id)
      .slice(0, safeLimit)
      .map((movement) => this.formatMovement(movement));
  }

  seedDemoData() {
    if (this.state.products.length > 0 || this.state.movements.length > 0) {
      throw new Error("Demo stock is already loaded or you have existing data.");
    }

    this.stockIn({
      barcode: "DEMO-1001",
      product_name: "Demo Widget",
      location: "Main Warehouse",
      quantity: 25,
      note: "Demo stock",
    });
    this.stockIn({
      barcode: "DEMO-2002",
      product_name: "Demo Cable",
      location: "Receiving",
      quantity: 12,
      note: "Demo stock",
    });
    this.transfer({
      barcode: "DEMO-1001",
      from_location: "Main Warehouse",
      to_location: "Storefront",
      quantity: 5,
      note: "Demo transfer",
    });
  }

  clearData() {
    this.state = emptyState();
    this.persist();
  }

  ensureProduct(barcode, productName) {
    const existing = this.findProductByBarcode(barcode);
    if (existing) {
      if (productName && productName !== existing.name) {
        existing.name = productName;
      }
      return existing;
    }

    const product = {
      id: this.state.nextIds.product++,
      barcode,
      name: productName,
      sku: null,
      created_at: nowIso(),
    };
    this.state.products.push(product);
    return product;
  }

  ensureLocation(name) {
    const existing = this.findLocationByName(name);
    if (existing) {
      return existing;
    }

    const location = {
      id: this.state.nextIds.location++,
      name,
      created_at: nowIso(),
    };
    this.state.locations.push(location);
    return location;
  }

  increaseStock(productId, locationId, quantity) {
    let level = this.findStockLevel(productId, locationId);
    if (!level) {
      level = {
        product_id: productId,
        location_id: locationId,
        quantity: 0,
      };
      this.state.stockLevels.push(level);
    }
    level.quantity += quantity;
  }

  decreaseStock(productId, locationId, quantity) {
    const level = this.findStockLevel(productId, locationId);
    const currentQuantity = level ? level.quantity : 0;
    if (currentQuantity < quantity) {
      throw new Error(`Only ${currentQuantity} units available at this location`);
    }
    level.quantity -= quantity;
  }

  recordMovement(details) {
    const movement = {
      id: this.state.nextIds.movement++,
      ...details,
      created_at: nowIso(),
    };
    this.state.movements.push(movement);
    return movement;
  }

  formatMovement(movement) {
    const product = this.findProductById(movement.product_id);
    return {
      id: movement.id,
      movement_type: movement.movement_type,
      barcode: product?.barcode || "",
      product_name: product?.name || "",
      from_location: this.findLocationById(movement.from_location_id)?.name || "",
      to_location: this.findLocationById(movement.to_location_id)?.name || "",
      quantity: movement.quantity,
      note: movement.note,
      created_at: new Date(movement.created_at).toLocaleString(),
    };
  }

  findProductByBarcode(barcode) {
    return this.state.products.find((product) => product.barcode === barcode);
  }

  findProductById(id) {
    return this.state.products.find((product) => product.id === id);
  }

  findLocationByName(name) {
    return this.state.locations.find((location) => location.name === name);
  }

  findLocationById(id) {
    return this.state.locations.find((location) => location.id === id);
  }

  findStockLevel(productId, locationId) {
    return this.state.stockLevels.find(
      (level) => level.product_id === productId && level.location_id === locationId,
    );
  }

  persist() {
    saveState(this.state);
  }
}

export function createInventoryStore() {
  return new LocalInventoryStore();
}
