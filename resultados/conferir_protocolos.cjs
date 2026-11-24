const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { tmpdir } = require("node:os");
const { chromium } = require(process.env.VETOR_PLAYWRIGHT || "playwright");
const url = `http://127.0.0.1:${process.env.VETOR_PORT || "8501"}`;
const pasta = process.env.VETOR_PASTA_PRINTS || path.join(tmpdir(), "vetor-protocolos");

async function main() {
  await fs.mkdir(pasta, { recursive: true });
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--no-proxy-server", "--disable-background-networking"]
  });
  try {
    const ctx = await browser.newContext({
      viewport:{width: 1250, height: 1200}, deviceScaleFactor: 2, serviceWorkers: "block"
    });
    const externos = [];
    await ctx.route("**/*", route => {
      if (new URL(route.request().url()).origin === url) return route.continue();
      externos.push(route.request().url());
      return route.abort();
    });
    const page = await ctx.newPage();
    page.setDefaultTimeout(75000);
    const erros = [];
    page.on("pageerror", e => erros.push(e.message));
    page.on("response", r => { if(r.status() >= 400) erros.push(r.status() + " " + r.url()); });
    let atualizacao = 0;
    page.on("websocket", socket => socket.on("framereceived", () => { atualizacao = Date.now(); }));
    const repouso = async () => {
      const fim = Date.now() + 3000;
      while (Date.now() < fim && Date.now() - atualizacao < 260) await page.waitForTimeout(40);
    };
    const clicar = async elemento => { await repouso(); await elemento.click(); };
    const screenshot = nome => path.join(pasta, nome + ".png");
    const registrar = async (nome, elemento) => {
      await repouso();
      await page.waitForTimeout(900);
      for (let i = 0; i < 20; i++) {
        const opaco = await elemento.evaluate(el => {
          let opac = 1;
          while (el) {
            opac *= Number(getComputedStyle(el).opacity);
            el = el.parentElement;
          }
          return opac >= 0.98;
        });
        if (opaco) break;
        if (i === 19) throw new Error("Opacidade instável em " + nome);
        await page.waitForTimeout(150);
      }
      await elemento.screenshot({ path: screenshot(nome), scale: "device", animations: "disabled" });
      console.log("SALVO", nome);
    };
    const regiao = async (nome, topo, fim, moldura) => {
      await repouso();
      await topo.evaluate(el => el.scrollIntoView({ block: "start" }));
      const [inicio, final, area] = await Promise.all([topo.boundingBox(), fim.boundingBox(), moldura.boundingBox()]);
      const viewport = page.viewportSize();
      const x = Math.max(0, Math.floor(area.x));
      const y = Math.max(0, Math.floor(inicio.y - 8));
      const largura = Math.min(viewport.width - x, Math.ceil(area.width));
      const altura = Math.min(viewport.height - y, Math.ceil(final.y + final.height + 9 - y));
      assert.ok(altura > 80 && largura > 80, JSON.stringify({inicio,final,area,largura,altura}));
      await page.screenshot({path:screenshot(nome),clip:{x,y,width:largura,height:altura},scale:"device",animations:"disabled"});
      console.log("SALVO", nome);
    };
    await page.goto(url, { waitUntil:"domcontentloaded" });
    const fluxo = page.locator('iframe[title*="streamlit_flow"]');
    const iframe = page.frameLocator('iframe[title*="streamlit_flow"]');
    const no = id => iframe.getByTestId(`rf__node-${id}`);
    const painel = page.locator(".st-key-propriedades");
    const inspecao = page.locator(".st-key-inspecao");
    const escolher = async (campo, opcao) => {
      await clicar(painel.getByTestId("stSelectbox").filter({hasText:campo}).getByRole("combobox"));
      await clicar(page.getByRole("option", {name:opcao,exact:true}));
    };
    const selecionar = async (id, texto) => {
      const alvo=painel.getByText(texto,{exact:true}).first();
      for(let tentativa=0; tentativa<5; tentativa++){
        await page.getByTestId("stMain").evaluate(el=>el.scrollTo(0,0));
        await clicar(no(id));
        if(await alvo.waitFor({timeout:6000}).then(()=>true).catch(()=>false)) return;
      }
      await alvo.waitFor();
    };
    const executar = async (modelo, rmse, protocolo) => {
      await clicar(page.getByRole("button", {name:"Executar fluxo",exact:true}));
      await inspecao.getByText("1. " + modelo,{exact:true}).waitFor({timeout:55000});
      await inspecao.getByText(rmse,{exact:true}).waitFor();
      const rotulo = inspecao.getByText(protocolo).first();
      await rotulo.waitFor();
      assert.equal(await inspecao.locator("table.dados").first().locator("tbody tr").count(), 5);
      console.log(await rotulo.innerText(), modelo, rmse);
    };

    await no("base").waitFor();
    await page.getByRole("img", {name:"VETOR",exact:true}).waitFor();
    await iframe.locator("body").evaluate(el => el.ownerDocument.fonts.ready);
    assert.equal(await iframe.locator(".react-flow__node").count(), 9);
    assert.equal(await iframe.locator(".react-flow__edge").count(), 12);
    for (const id of ["m1","m2","m3","m4","m5"]) await no(id).waitFor();
    console.log("ABERTO E EXPLORADO", url, "9 blocos e 12 conexões");
    await registrar("fluxo", fluxo);

    await selecionar("base","Dados");
    await inspecao.getByText("1.742",{exact:true}).first().waitFor();
    await inspecao.getByText("850",{exact:true}).first().waitFor();
    await page.mouse.move(5, 105);
    const graficosBase = inspecao.getByTestId("stVegaLiteChart");
    await graficosBase.last().locator("svg.marks,canvas.marks").waitFor();
    await regiao("dados", inspecao.getByRole("heading",{name:"Dados",exact:true}),
                 graficosBase.first(), inspecao);
    await selecionar("preparo","Preparação");
    await inspecao.getByText("892",{exact:true}).first().waitFor();

    await page.setViewportSize({width: 1500, height: 1200});
    await regiao("preparacao", inspecao.getByText(/excluídas adicionalmente por ausência da taxa inicial/), inspecao.getByText("Proteção contra vazamento",{exact:true}), inspecao);
    await selecionar("m3","Modelos");
    await clicar(painel.getByText("Configuração acadêmica",{exact:true}));
    await painel.getByText(/Mínimos quadrados ordinários/).waitFor();
    await painel.locator("details[open]").waitFor();
    await registrar("modelo", painel);
    await page.setViewportSize({width: 1250, height: 1200});

    await executar("M3","3,221",/Execução atual.*80\/20.*170 escolas avaliadas/);
    const ranking = inspecao.locator("table.dados").first();
    const titulos = (await ranking.locator("thead").innerText()).trim();
    for (const texto of ["MAE", "RMSE", "R²"]) assert.ok(titulos.includes(texto));
    const contagem = inspecao.getByText("Acadêmico · cenário A",{exact:true});
    await regiao("teste", contagem, ranking, inspecao);
    async function resultados(identificador) {
      await inspecao.getByText("Referências estatísticas e partições",{exact:true}).evaluate(el=>{
        const details=el.closest("details");
        if (!details || !details.open) el.click();
      });
      const exp=inspecao.getByTestId("stExpander").filter({hasText:"Referências estatísticas e partições"});
      await exp.locator("table.dados").nth(1).waitFor();
      const obter=async t=> t.locator("tbody tr").evaluateAll(tr=>tr.map(x=>Array.from(x.cells, c=>c.textContent.trim())));
      const item={id:identificador, ranking:await obter(inspecao.locator("table.dados").first()),referencias:await obter(exp.locator("table.dados").first()),divisoes:await obter(exp.locator("table.dados").nth(1))};
      console.log("TABELA "+JSON.stringify(item));
    }
    await resultados("80/20 A");

    await clicar(inspecao.getByRole("tab",{name:"Diagnóstico por escola"}));
    const seletor = inspecao.getByTestId("stSelectbox").filter({hasText:"Modelo para os gráficos"});
    await seletor.getByText("M3",{exact:true}).waitFor();
    const faixa = inspecao.getByText(/Taxa observada abaixo de 90%/);
    await faixa.waitFor();
    for (const item of await inspecao.getByTestId("stVegaLiteChart").all()) {
      if (await item.isVisible()) await item.locator("svg.marks,canvas.marks").waitFor();
    }
    await regiao("erros", seletor, faixa, inspecao);
    console.log(await faixa.innerText());

    await selecionar("avaliador","Avaliação");
    await escolher("Protocolo","Validação cruzada de 5 divisões");
    await executar("M4","3,211",/Execução atual.*5 divisões.*680 escolas avaliadas/);
    await regiao("cruzada", inspecao.getByText(/Execução atual.*5 divisões.*680 escolas avaliadas/), inspecao.locator("table.dados").first(), inspecao);
    await resultados("Cruzada A");
    await selecionar("avaliador","Avaliação");
    await escolher("Protocolo","Validação aninhada (histórica)");
    await no("avaliador").getByText("Aninhada · 5 × 4",{exact:true}).waitFor();
    await executar("M5","3,491",/Execução atual.*aninhada.*850 escolas avaliadas/);
    await resultados("Aninhada A");
    const regra = inspecao.getByText("Seleção interna",{exact:true});
    await regra.waitFor();
    await inspecao.getByText("3,941",{exact:true}).waitFor();
    const painelRef = inspecao.getByTestId("stExpander").filter({hasText:"Referências estatísticas e partições"});
    await painelRef.getByText("Escolha nas divisões internas",{exact:true}).waitFor();
    await painelRef.getByTestId("stDataFrame").locator("canvas").first().waitFor();
    await registrar("aninhada", painelRef);
    assert.deepEqual(erros, []);
    assert.deepEqual(externos, []);
    console.log("AUDITORIA OK, todos os seis arquivos registrados");
  } finally { await browser.close(); }
}
main().catch(e=>{ console.error(e); process.exitCode=1; });
