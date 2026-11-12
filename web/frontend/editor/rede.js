// POST JSON com CSRF. Resolve sempre com {status, dados} (dados = {} se a resposta não for JSON).
export async function postarJSON(url, corpo, csrf) {
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || "", Accept: "application/json" },
      body: JSON.stringify(corpo),
    });
  } catch (e) {
    return { status: 0, dados: { erros: ["Sem conexão com o servidor: " + e.message] } };
  }
  let dados = {};
  try {
    dados = await resp.json();
  } catch (e) {
    dados = { erros: [`Resposta inesperada do servidor (HTTP ${resp.status}).`] };
  }
  return { status: resp.status, dados };
}
