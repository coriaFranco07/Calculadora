async function readJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No se pudo cargar ${path} (${response.status}).`);
  }
  return response.json();
}

function unwrap(payload) {
  return payload?.records ?? payload ?? [];
}

export async function loadAuditCatalogs() {
  const [conceptos, reglas, mapeoAfip, formulas, convenio] = await Promise.all([
    readJson("./data/conceptos.json"),
    readJson("./data/reglas.json"),
    readJson("./data/mapeo_afip.json"),
    readJson("./data/formulas.json"),
    readJson("./data/convenio_244_94.json")
  ]);

  return {
    conceptos: unwrap(conceptos),
    reglas: unwrap(reglas),
    mapeoAfip: unwrap(mapeoAfip),
    formulas: unwrap(formulas),
    convenio: unwrap(convenio),
    metadata: {
      conceptosVersion: conceptos?.version || "sin-version",
      reglasVersion: reglas?.version || "sin-version",
      mapeoVersion: mapeoAfip?.version || "sin-version",
      formulasVersion: formulas?.version || "sin-version",
      convenioVersion: convenio?.version || "sin-version"
    }
  };
}

export async function loadSamplePayload() {
  return readJson("./data/sample_auditoria.json");
}
