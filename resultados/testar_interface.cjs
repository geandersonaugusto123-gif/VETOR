const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { tmpdir } = require("node:os");
const { chromium } = require(process.env.VETOR_PLAYWRIGHT || "playwright");

const base = `http://127.0.0.1:${process.env.VETOR_PORT || "8501"}`;
const pasta = process.env.VETOR_PASTA_PRINTS || path.join(tmpdir(), "vetor-interface");
const width = Number(process.env.VETOR_WIDTH || 1440);
const height = Number(process.env.VETOR_HEIGHT || 900);
const breve = process.env.VETOR_BREVE === "1";
const celular = width < 600;
const soCapturas = process.env.VETOR_SO_PRINTS === "1";

async function testar() {
  await fs.mkdir(pasta, { recursive: true });
  const navegador = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--no-proxy-server", "--disable-background-networking"],
  });
  let pagina;
  try {
    const contexto = await navegador.newContext({
      viewport: { width, height }, serviceWorkers: "block", hasTouch: celular, isMobile: celular,
    });
    const externos = [];
    const erros = [];
    await contexto.route("**/*", route => {
      if (new URL(route.request().url()).origin === base) return route.continue();
      externos.push(route.request().url());
      return route.abort();
    });
    pagina = await contexto.newPage();
    const toque = celular ? await contexto.newCDPSession(pagina) : null;
    pagina.setDefaultTimeout(75000);
    pagina.on("pageerror", e => erros.push(e.message));
    pagina.on("response", res => { if (res.status() >= 400) erros.push(`${res.status()} ${res.url()}`); });
    const websocket = { enviados: 0, recebidos: 0 };
    let ultimaMensagem = Date.now();
    pagina.on("websocket", socket => {
      socket.on("framesent", () => websocket.enviados += 1);
      socket.on("framereceived", () => { websocket.recebidos += 1; ultimaMensagem = Date.now(); });
    });
    const aguardarRenderizacao = async () => {
      const limite = Date.now() + 3000;
      while (Date.now() < limite && Date.now() - ultimaMensagem < 220) await pagina.waitForTimeout(40);
    };
    const acionar = async elemento => {
      await aguardarRenderizacao();
      return celular ? elemento.tap() : elemento.click();
    };
    await pagina.goto(base);
    const quadro = pagina.frameLocator('iframe[title*="streamlit_flow"]');
    const no = id => quadro.getByTestId(`rf__node-${id}`);
    const painel = pagina.locator(".st-key-propriedades");
    const inspecao = pagina.locator(".st-key-inspecao");
    const salvar = nome => pagina.screenshot({ path: path.join(pasta, nome + ".png"), animations: "disabled" });
    const inicio = () => pagina.getByTestId("stMain").evaluate(el => el.scrollTop = 0);
    const scroll = el => el.evaluate(elem => elem.scrollIntoView({ block: "start" }));
    const botaoExecutar = pagina.getByRole("button", { name: "Executar fluxo", exact: true });
    const alertaSucesso = pagina.getByText(/Execução concluída/).first();
    const totalArestas = async (n) => {
      const arestas = quadro.locator(".react-flow__edge");
      if (n) await arestas.nth(n - 1).waitFor({ state: "attached" });
      await arestas.nth(n).waitFor({ state: "detached" });
      assert.equal(await arestas.count(), n);
    };
    const selecionar = async (id, texto) => {
      const alvo = painel.getByText(texto, { exact: typeof texto === "string" }).first();
      for(let tentativa=0; tentativa<5; tentativa++) {
        await inicio();
        await acionar(no(id));
        if(await alvo.waitFor({timeout:6000}).then(()=>true).catch(()=>false)) return;
      }
      await alvo.waitFor();
    };
    const escolher = async (campo, opcao) => {
      await acionar(painel.getByTestId("stSelectbox").filter({ hasText: campo }).getByRole("combobox"));
      await acionar(pagina.getByRole("option", { name: opcao, exact: true }));
    };
    const executar = async (capturar = false) => {
      const captura = capturar && pagina.getByText(/Preparando as partições e treinando os modelos conectados/).first()
        .waitFor({ timeout: 3500 }).then(async () => { await salvar("04_execucao"); return true; }).catch(() => false);
      await acionar(botaoExecutar);
      await alertaSucesso.waitFor({ timeout: 45000 });
      if (capturar && !(await captura)) await salvar("04_execucao");
    };
    const resultado = async (nome, rmse, modelos, idResultado = "resultados") => {
      if (!(await inspecao.getByText(nome, { exact: true }).isVisible())) await selecionar(idResultado, "Resultados");
      await inspecao.getByText(nome, { exact: true }).waitFor();
      await inspecao.getByText(rmse, { exact: true }).waitFor();
      const tabela = inspecao.locator("table.dados, table").first();
      const titulos = await tabela.locator("thead th").allTextContents();
      for (const metrica of ["MAE", "RMSE", "R²"]) assert.ok(titulos.some(titulo => titulo.includes(metrica)));
      const linhas = tabela.locator("tbody tr");
      assert.equal(await linhas.count(), modelos.length);
      const conteudo = (await linhas.allTextContents()).join(" ");
      for (const codigo of ["M1", "M2", "M3", "M4", "M5"]) assert.equal(conteudo.includes(codigo), modelos.includes(codigo));
    };
    const conectar = async (origem, destino) => {
      await aguardarRenderizacao();
      const saida = no(origem).locator(".react-flow__handle.source");
      const entrada = no(destino).locator(".react-flow__handle.target");
      await saida.scrollIntoViewIfNeeded();
      const [s, t] = await Promise.all([saida.boundingBox(), entrada.boundingBox()]);
      assert.ok(s && t, `Portas ausentes de ${origem} para ${destino}`);
      await arrastar(pagina, s.x + s.width / 2, s.y + s.height / 2, t.x + t.width / 2, t.y + t.height / 2, toque);
    };
    const clicarAresta = async (id) => {
      await aguardarRenderizacao();
      const iframe = await pagina.locator('iframe[title*="streamlit_flow"]').boundingBox();
      const trecho = quadro.getByTestId(`rf__edge-${id}`).locator(".react-flow__edge-interaction");
      const ponto = await trecho.evaluate(path => {
        const matriz = path.getScreenCTM();
        const tamanho = path.getTotalLength();
        for (const fracao of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) {
          const local = path.getPointAtLength(tamanho * fracao).matrixTransform(matriz);
          if (path.ownerDocument.elementFromPoint(local.x, local.y)?.closest(".react-flow__edge") === path.parentElement) {
            return { x: local.x, y: local.y };
          }
        }
        throw new Error("A aresta está encoberta por outro elemento.");
      });
      if (celular) await pagina.touchscreen.tap(iframe.x + ponto.x, iframe.y + ponto.y);
      else await pagina.mouse.click(iframe.x + ponto.x, iframe.y + ponto.y);
    };

    if (process.env.VETOR_DUMP === "1") {
      await quadro.locator(".react-flow").waitFor();
      console.log(await pagina.locator("body").innerText());
      console.log(await quadro.locator("body").innerText());
      console.log(await quadro.locator(".react-flow__node, .react-flow__edge").evaluateAll(els => els.map(el => ({ id: el.dataset.id, testid: el.dataset.testid, box: el.getBoundingClientRect().toJSON() }))));
      await pagina.screenshot({ path: path.join(__dirname, "debug-abertura.png") });
      return;
    }
    if (process.env.VETOR_EXEC === "1") {
      await botaoExecutar.waitFor();
      if (process.env.VETOR_EXEC_M3 === "1") {
        await selecionar("m3", "Modelos");
        await painel.getByText("Configuração acadêmica", { exact: true }).click();
        await painel.getByText(/Soma o intercepto e as contribuições/).waitFor();
      }
      for (let i = 1; i <= 3; i += 1) {
        console.log("Clicando", i, { ...websocket }, await botaoExecutar.evaluate(el => {
          const rect = el.getBoundingClientRect();
          const alvo = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
          return { desabilitado: el.disabled, alvo: alvo?.outerHTML.slice(0, 200) };
        }));
        await botaoExecutar.click();
        const resposta = await alertaSucesso.waitFor({ timeout: 6000 }).then(() => true).catch(() => false);
        console.log("Execução concluída visível", resposta, { ...websocket });
        if (resposta) break;
      }
      console.log((await pagina.locator("body").innerText()).slice(0, 2300));
      return;
    }
    await no("base").waitFor();
    assert.equal(await quadro.locator(".react-flow__node").count(), 9);
    await totalArestas(12);
    await pagina.getByRole("img", { name: "VETOR", exact: true }).waitFor();
    await quadro.locator("body").evaluate(el => el.ownerDocument.fonts.ready);
    await no("m3").getByText(/M3/).first().waitFor();
    if (!breve) { await aguardarRenderizacao(); await salvar("01_interface"); }
    await selecionar("base", /^(Dados|Dados CSV)$/);
    await inspecao.getByText("1.742", { exact: true }).first().waitFor();
    await inspecao.getByText("850", { exact: true }).first().waitFor();
    if (!breve) {
      await inspecao.getByTestId("stVegaLiteChart").nth(1).locator("svg.marks,canvas.marks").waitFor();
      await inspecao.getByTestId("stDataFrame").first().locator("canvas").first().waitFor();
      await scroll(inspecao);
      await salvar("02_dados");
    }
    await selecionar("preparo", "Preparação");
    await inspecao.getByText("892", { exact: true }).first().waitFor();
    await selecionar("m3", /^(Modelos|Modelo de IA)$/);
    await acionar(painel.getByText("Configuração acadêmica", { exact: true }));
    await painel.getByText(/Soma o intercepto e as contribuições/).waitFor();
    if (!breve) {
      await painel.getByText(/Mínimos quadrados ordinários, com intercepto e sem regularização/).waitFor();
      await inicio();
      await salvar("03_modelos");
    }
    await executar(!breve);
    const cinco = ["M1", "M2", "M3", "M4", "M5"];
    await resultado("1. M3", "3,221", cinco);
    const tabelaA = inspecao.locator("table.dados").first();
    const linhasA = await tabelaA.innerText();
    await executar();
    await resultado("1. M3", "3,221", cinco);
    assert.equal(await inspecao.locator("table.dados").first().innerText(), linhasA);
    const grafico = inspecao.getByTestId("stVegaLiteChart").first();
    for (const metrica of ["MAE", "R²", "RMSE"]) {
      await inspecao.locator("label").filter({hasText: new RegExp("^" + metrica + "$")}).click();
      await grafico.locator("svg.marks,canvas.marks").waitFor();
      await pagina.waitForFunction(nome => [...document.querySelectorAll('.st-key-inspecao [data-testid=stVegaLiteChart] svg')].some(e => e.textContent.includes(nome)), metrica === "R²" ? "R²" : metrica + " (p.p.)");
    }
    console.log("Repetição no mesmo protocolo: tabela idêntica. O eixo mudou para MAE, R² e RMSE.");
    if (soCapturas) {
      await selecionar("avaliador", "Avaliação");
      await escolher("Protocolo", "Validação cruzada de 5 divisões");
      await no("avaliador").getByText("Cruzada · 5 divisões", { exact: true }).waitFor();
      await executar();
      await resultado("1. M4", "3,211", cinco);
      await scroll(inspecao);
      await inspecao.getByTestId("stVegaLiteChart").first().locator("svg.marks,canvas.marks").waitFor();
      await salvar("05_resultados");
      assert.deepEqual(erros, []);
      assert.deepEqual(externos, []);
      console.log("Cinco capturas desktop da sessão acima, protocolos 80/20 e CV5 conferidos.");
      return;
    }
    if (!breve) {
      await inicio();
      await conectar("base", "avaliador");
      await painel.getByText(/Conexão incompatível com Avaliação/).waitFor();
      await totalArestas(12);
      await resultado("1. M3", "3,221", cinco);
      console.log("Ligação inválida rejeitada pelo navegador; bancada e resultado anteriores preservados.");

      await clicarAresta("m5:avaliador");
      await acionar(pagina.getByRole("button", { name: /Remover conexão/ }));
      await totalArestas(11);
      await alertaSucesso.waitFor({ state: "hidden" });
      await selecionar("resultados", "Resultados");
      await inspecao.getByText(/Execute o fluxo para calcular os resultados/).waitFor();
      await executar();
      await resultado("1. M3", "3,221", cinco.slice(0, 4));
      console.log("A conexão removida excluiu M5 e invalidou a execução anterior.");

      await inicio();
      const m5 = no("m5");
      const estilo = await m5.getAttribute("style");
      const posicao = await m5.boundingBox();
      const x = posicao.x + posicao.width / 2;
      const y = posicao.y + posicao.height / 2;
      await arrastar(pagina, x, y, x - 35, y + 23, toque);
      assert.notEqual(await m5.getAttribute("style"), estilo);
      await conectar("m5", "avaliador");
      await totalArestas(12);

      await selecionar("avaliador", "Avaliação");
      await escolher("Protocolo", "Validação cruzada de 5 divisões");
      await no("avaliador").getByText("Cruzada · 5 divisões", { exact: true }).waitFor();
      await executar();
      await resultado("1. M4", "3,211", cinco);
      await scroll(inspecao);
      await inspecao.getByTestId("stVegaLiteChart").first().locator("svg.marks,canvas.marks").waitFor();
      await salvar("05_resultados");
      console.log("Arraste de nó, reconexão de portas e cinco modelos em validação cruzada conferidos.");

      await inspecao.getByRole("tab", { name: "Diagnóstico por escola" }).click();
      await inspecao.getByText(/Escolas com os maiores erros absolutos/).waitFor();
      await scroll(inspecao);
      await aguardarRenderizacao();
      await salvar("06_erros");

      await selecionar("avaliador", "Avaliação");
      await escolher("Protocolo", "Validação aninhada (histórica)");
      await no("avaliador").getByText("Aninhada · 5 × 4", { exact: true }).waitFor();
      await executar();
      await resultado("1. M5", "3,491", cinco);
      console.log("Validação aninhada executada no navegador com os cinco candidatos.");

      await selecionar("base", /^(Dados|Dados CSV)$/);
      const origem = painel.getByTestId("stSelectbox").filter({ hasText: "Origem da base" });
      if (await origem.isVisible()) await escolher("Origem da base", "CSV compatível");
      const upload = painel.locator('input[type="file"]');
      await upload.waitFor({ state: "attached" });
      await upload.setInputFiles(path.join(__dirname, "..", "dados", "02_educacao.csv"));
      const usarArquivo = painel.getByRole("button", { name: "Usar arquivo", exact: true });
      await acionar(usarArquivo);
      await painel.getByText(/Arquivo ativo · 02_educacao.csv/).waitFor();
      await inspecao.getByText("1.742", { exact: true }).first().waitFor();
      await upload.setInputFiles({ name: "invalido.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
      const carregar = painel.getByRole("button", { name: /^(Carregar CSV|Usar arquivo)$/ });
      if (await carregar.count()) await acionar(carregar);
      await painel.getByText(/Colunas obrigatórias ausentes/i).waitFor();
      await painel.getByText(/Arquivo ativo · 02_educacao.csv/).waitFor();
      await inspecao.getByText("1.742", { exact: true }).first().waitFor();
      await selecionar("avaliador", "Avaliação");
      await escolher("Protocolo", "Teste 80/20");
      await no("avaliador").getByText("Teste 80/20", { exact: true }).waitFor();
      await executar();
      await inspecao.getByText(/Exploratório · CSV importado/).first().waitFor();
      await inspecao.getByText(/170 escolas avaliadas/).first().waitFor();
      console.log("CSV importado reavaliado como exploratório. Substituição inválida preservou a base ativa.");

      await acionar(pagina.getByRole("button", { name: "Novo fluxo", exact: true }));
      await no("base").waitFor({ state: "detached" });
      if (!(await botaoExecutar.isDisabled())) {
        await acionar(botaoExecutar);
        await pagina.getByTestId("stAlert").filter({ hasText: /conect|adicione|fluxo|avaliação/i }).first().waitFor();
      }
      const ids = [];
      const paleta = pagina.locator(".st-key-ferramentas");
      for (const nome of ["Dados", "Preparação", "Modelos", "Avaliação", "Resultados"]) {
        await acionar(paleta.getByRole("button", { name: nome, exact: true }));
        const ultimo = quadro.locator(".react-flow__node").nth(ids.length);
        await ultimo.waitFor();
        ids.push(await ultimo.getAttribute("data-id"));
        await painel.getByText(nome, { exact: true }).first().waitFor();
        if (nome === "Modelos") {
          await escolher("Algoritmo", "M1 · Regressão linear simples");
          await ultimo.getByText("M1", { exact: true }).waitFor();
        }
      }
      await inicio();
      for (let i = 0; i < ids.length - 1; i += 1) {
        await conectar(ids[i], ids[i + 1]);
        await totalArestas(i + 1);
        await aguardarRenderizacao();
      }
      await executar();
      await resultado("1. M1", "3,382", ["M1"], ids.at(-1));
      await selecionar(ids[2], "Modelos");
      await escolher("Algoritmo", "M2 · Regressão pelo perfil");
      await no(ids[2]).getByText("M2", { exact: true }).waitFor();
      await selecionar(ids[1], "Preparação");
      await escolher("População", "Cenário B · perfil ampliado");
      await no(ids[1]).getByText("Cenário B", { exact: true }).waitFor();
      await executar();
      await resultado("1. M2", "2,721", ["M2"], ids.at(-1));
      await inspecao.getByText(/349 escolas avaliadas/).first().waitFor();
      const titleB=inspecao.getByText(/Execução atual.*349 escolas avaliadas/).first();
      await titleB.scrollIntoViewIfNeeded();
      await pagina.waitForTimeout(1000);
      const tabelaB=inspecao.locator("table.dados").first();
      await titleB.evaluate(el=>el.scrollIntoView({block:"start"}));
      const [top,bottom,painelB] = await Promise.all([titleB.boundingBox(),tabelaB.boundingBox(),inspecao.boundingBox()]);
      const left=Math.max(0,Math.floor(painelB.x + 12));
      const topoB=Math.max(0,Math.floor(top.y-6));
      await pagina.screenshot({path:path.join(pasta,"cenario_b.png"),animations:"disabled",
        clip:{x:left,y:topoB,width:Math.ceil(painelB.width/2),height:Math.ceil(bottom.y+bottom.height+10-topoB)}});
      const bRank=await inspecao.locator("table.dados").first().locator("tbody tr").evaluateAll(tr=>tr.map(x=>Array.from(x.cells,c=>c.textContent.trim())));
      await acionar(inspecao.getByText("Referências estatísticas e partições",{exact:true}));
      const exp=inspecao.getByTestId("stExpander").filter({hasText:"Referências estatísticas e partições"});
      const ler=async idx=>exp.locator("table.dados").nth(idx).locator("tbody tr").evaluateAll(tr=>tr.map(x=>Array.from(x.cells,c=>c.textContent.trim())));
      const referenciasB = await ler(0);
      assert.deepEqual(referenciasB.find(linha => linha[0] === "Mediana do treino"),
        ["Mediana do treino", "1,408", "3,154", "−0,249"]);
      console.log("TABELA "+JSON.stringify({id:"80/20 B",ranking:bRank,referencias:referenciasB,divisoes:await ler(1)}));
      console.log("No cenário B o navegador executou somente M2 e exibiu 349 escolas de teste.");
      await acionar(pagina.getByRole("button", { name: "Abrir exemplo", exact: true }));
      await no("base").waitFor();
      await totalArestas(12);
      console.log("A bancada vazia não executa. Um fluxo do zero e o retorno ao exemplo passaram.");
    }

    assert.equal(await pagina.getByTestId("stException").count(), 0);
    assert.deepEqual(erros, []);
    assert.deepEqual(externos, []);
    assert.ok(await pagina.evaluate(() => document.querySelector('[data-testid="stMain"]').scrollWidth <= innerWidth));
    assert.ok(await quadro.locator("html").evaluate(el => el.scrollWidth <= el.clientWidth));
    if (breve) {
      await inicio();
      await pagina.screenshot({ path: path.join(__dirname, `largura-${width}.png`) });
      await scroll(inspecao);
      await inspecao.getByTestId("stVegaLiteChart").first().locator("svg.marks,canvas.marks").waitFor();
      await pagina.screenshot({ path: path.join(__dirname, `largura-${width}-resultados.png`) });
      if (celular && process.env.VETOR_CELULAR_COMPLETO === "1") {
        await inicio();
        await clicarAresta("m5:avaliador");
        await acionar(pagina.getByRole("button", { name: /Remover conexão/ }));
        await totalArestas(11);
        await inicio();
        const modelo = no("m5");
        const estilo = await modelo.getAttribute("style");
        const box = await modelo.boundingBox();
        await arrastar(pagina, box.x + box.width / 2, box.y + box.height / 2,
          box.x + box.width / 2 - 15, box.y + box.height / 2 + 20, toque);
        assert.notEqual(await modelo.getAttribute("style"), estilo);
        await conectar("m5", "avaliador");
        await totalArestas(12);
        await selecionar("avaliador", "Avaliação");
        await escolher("Protocolo", "Validação cruzada de 5 divisões");
        await no("avaliador").getByText("Cruzada · 5 divisões", { exact: true }).waitFor();
        await executar();
        await resultado("1. M4", "3,211", cinco);
        assert.deepEqual(erros, []);
        assert.deepEqual(externos, []);
        console.log("Celular: arraste, reconexão e validação cruzada por toque verificados.");
      }
    }
    console.log(`${width}×${height}: execução local, abertura, métricas e ausência de requisições externas verificadas.`);
  } catch (erro) {
    if (pagina) {
      await pagina.screenshot({ path: path.join(pasta, `falha-${width}.png`), fullPage: true }).catch(() => {});
      console.error((await pagina.locator("body").innerText().catch(() => "")).slice(0, 2300));
    }
    throw erro;
  } finally {
    await navegador.close();
  }
}

async function arrastar(pagina, inicioX, inicioY, fimX, fimY, toque) {
  if (toque) {
    await toque.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: inicioX, y: inicioY }] });
    for (let passo = 1; passo <= 18; passo += 1) {
      const x = inicioX + (fimX - inicioX) * passo / 18;
      const y = inicioY + (fimY - inicioY) * passo / 18;
      await toque.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y }] });
    }
    await toque.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    return;
  }
  await pagina.mouse.move(inicioX, inicioY);
  await pagina.mouse.down();
  await pagina.mouse.move(fimX, fimY, { steps: 18 });
  await pagina.mouse.up();
}

testar().catch(erro => { console.error(erro); process.exitCode = 1; });
