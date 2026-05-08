export function createGeminiClient(baseUrl = "") {
  async function health() {
    const response = await fetch(`${baseUrl}/health`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Health check fallo: ${response.status}`);
    }
    return response.json();
  }

  async function audit(summary) {
    const response = await fetch(`${baseUrl}/audit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(summary)
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Error ${response.status}`);
    }

    return response.json();
  }

  return { health, audit };
}
