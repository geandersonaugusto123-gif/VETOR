"""Editor e inspeção do fluxo experimental no Streamlit."""

from base64 import b64encode
from pathlib import Path
from time import time_ns
from uuid import uuid4

import streamlit as st
from streamlit_flow import StreamlitFlowEdge, StreamlitFlowNode, StreamlitFlowState, streamlit_flow

import fluxo
import motor
import paineis

PASTA = Path(__file__).resolve().parent
IMAGENS = PASTA / "imagens"
CORES = dict(dados="#83ACD4", preparar="#AA9BD1", modelo="#D9A441",
             avaliar="#78BCAE", resultados="#E4E7EB")
NOMES = fluxo.TITULOS
PROTOCOLOS = {
    motor.TESTE: "Teste 80/20",
    motor.SIMPLES: "Validação cruzada de 5 divisões",
    motor.ANINHADA: "Validação aninhada (histórica)",
}
ss = st.session_state


def rotulo_no(tipo, config):
    detalhes = {
        "dados": "UEG · Goiás 2025" if config.get("fonte") == "ueg" else "CSV local",
        "preparar": "Cenário A" if config.get("cenario") == motor.COMPLETAS else "Cenário B",
        "avaliar": {motor.TESTE: "Teste 80/20", motor.SIMPLES: "Cruzada · 5 divisões",
                    motor.ANINHADA: "Aninhada · 5 × 4"}.get(config.get("metodo")),
        "resultados": "MAE, RMSE e R²",
    }
    if tipo == "modelo":
        codigo = config["codigo"]
        titulo, subtitulo = codigo, fluxo.MODELOS[codigo]
    else:
        titulo, subtitulo = NOMES[tipo], detalhes[tipo]
    return (f'<div style="margin:0"><strong>{titulo}</strong><br>'
            f'<span style="color:#CCD0D6">{subtitulo}</span></div>')


def criar_no(id_no, tipo, x, y, config):
    config = fluxo.editar_config(tipo, config)
    return StreamlitFlowNode(
        id_no, (x, y), {"tipo": tipo, "config": config, "content": rotulo_no(tipo, config)},
        node_type={"dados": "input", "resultados": "output"}.get(tipo, "default"),
        source_position="right", target_position="left", selectable=True, connectable=True,
        style={"width": 156, "padding": "7px 9px", "fontSize": 15, "lineHeight": 1.3, "textAlign": "left",
               "background": "#1D2024", "color": "#F7F8FA", "borderRadius": 7,
               "border": "1px solid #343940", "borderLeft": f"4px solid {CORES[tipo]}"},
    )


def criar_aresta(identificador, origem, destino):
    return StreamlitFlowEdge(
        identificador, origem, destino, marker_end={"type": "arrowclosed", "color": "#A8ADB4"},
        style={"stroke": "#A8ADB4", "strokeWidth": 2},
    )


def substituir(exemplo=False):
    desenho = fluxo.exemplo() if exemplo else {"nos": [], "conexoes": []}
    nos = [criar_no(n["id"], n["tipo"], n["x"], n["y"], n["config"]) for n in desenho["nos"]]
    arestas = [
        criar_aresta(f"{origem}:{destino}", origem, destino)
        for origem, destino in ((e["origem"], e["destino"]) for e in desenho["conexoes"])
    ]
    ss.editor = StreamlitFlowState(nos, arestas)
    ss.publicado = ss.editor
    ss.tela = ss.get("tela", 0) + 1
    ss.selecao = None
    ss.anexos = {}
    ss.erros_csv = {}
    ss.pop("aviso_conexao", None)
    ss.pop("pedido", None)
    limpar_resultados()


def limpar_resultados():
    ss.pop("execucao", None)
    ss.pop("falha", None)


def atualizar_editor():
    # Só reenviamos o desenho ao iframe quando o Python muda um bloco ou conexão.
    timestamp = max(time_ns() // 1_000_000, ss.editor.timestamp + 1)
    ss.editor = StreamlitFlowState(ss.editor.nodes, ss.editor.edges, timestamp=timestamp)
    ss.publicado = ss.editor


def adicionar(tipo):
    existentes = [n.position["y"] for n in ss.editor.nodes if n.data["tipo"] == tipo]
    y = max(existentes) + 88 if existentes else 208
    ss.selecao = uuid4().hex
    ss.editor.nodes.append(criar_no(ss.selecao, tipo, fluxo.COLUNAS[tipo], y, {}))
    atualizar_editor()


def remover(identificador):
    ss.editor.nodes = [n for n in ss.editor.nodes if n.id != identificador]
    ss.editor.edges = [e for e in ss.editor.edges if identificador not in (e.id, e.source, e.target)]
    ss.anexos.pop(identificador, None)
    ss.erros_csv.pop(identificador, None)
    ss.pop("aviso_conexao", None)
    ss.selecao = None
    atualizar_editor()


def desenho_editor(estado):
    # O editor fornece os nós e as arestas. Posição e seleção não influenciam o treino.
    return {
        "nos": [{"id": n.id, "tipo": n.data["tipo"], "config": n.data["config"]} for n in estado.nodes],
        "conexoes": [{"origem": e.source, "destino": e.target} for e in estado.edges],
    }


def receber_editor(retorno):
    if retorno.timestamp <= ss.editor.timestamp:
        return
    anteriores = {e.id for e in ss.editor.edges}
    ss.editor = retorno
    if any(e.id not in anteriores for e in retorno.edges):
        ss.pop("aviso_conexao", None)
        try:
            fluxo.validar(desenho_editor(retorno))
        except fluxo.ErroFluxo as erro:
            ss.aviso_conexao = str(erro)
            retorno.edges = [e for e in retorno.edges if e.id in anteriores]
        else:
            retorno.edges = [e if e.id in anteriores else criar_aresta(e.id, e.source, e.target)
                             for e in retorno.edges]
            ss.selecao = retorno.selected_id
        atualizar_editor()
        st.rerun()
    if retorno.selected_id:
        ss.selecao = retorno.selected_id


def configurar(id_no, campo, chave):
    no = next(n for n in ss.editor.nodes if n.id == id_no)
    no.data["config"][campo] = ss[chave]
    no.data["content"] = rotulo_no(no.data["tipo"], no.data["config"])
    atualizar_editor()


def opcao_no(no, campo, titulo, opcoes, formatar=str):
    chave = f"{ss.tela}_{no.id}_{campo}"
    return st.selectbox(
        titulo, opcoes, index=opcoes.index(no.data["config"][campo]), format_func=formatar,
        key=chave, on_change=configurar, args=(no.id, campo, chave),
    )


def importar_arquivo(identificador, chave):
    arquivo = ss[chave]
    try:
        base = motor.importar_csv(arquivo.getvalue())
    except ValueError as erro:
        ss.erros_csv[identificador] = str(erro)
    else:
        ss.anexos[identificador] = (arquivo.name, base)
        ss.erros_csv.pop(identificador, None)
        limpar_resultados()


def propriedades(no):
    tipo = no.data["tipo"]
    chave = f"{ss.tela}_{no.id}"
    st.markdown(f"**{NOMES[tipo]}**")
    if tipo == "dados":
        opcoes = {"ueg": "Base original da UEG", "csv": "CSV compatível"}
        fonte = opcao_no(no, "fonte", "Origem da base", list(opcoes), opcoes.get)
        if fonte == "csv":
            chave_csv = f"csv_{chave}"
            arquivo = st.file_uploader("Arquivo CSV", type=["csv"], key=chave_csv)
            st.button("Usar arquivo", disabled=arquivo is None, key=f"carregar_{chave}",
                      on_click=importar_arquivo, args=(no.id, chave_csv))
            if erro := ss.erros_csv.get(no.id):
                st.error(erro)
            if anexo := ss.anexos.get(no.id):
                st.caption(f"Arquivo ativo · {anexo[0]}")
    elif tipo == "preparar":
        opcao_no(no, "cenario", "População", (motor.COMPLETAS, motor.AMPLIADA))
        st.caption("O cenário B avalia somente M2.")
    elif tipo == "modelo":
        codigo = opcao_no(no, "codigo", "Algoritmo", list(fluxo.MODELOS),
                          lambda m: f"{m} · {fluxo.MODELOS[m]}")
        with st.expander("Configuração acadêmica"):
            paineis.detalhe_modelo(codigo)
    elif tipo == "avaliar":
        opcao_no(no, "metodo", "Protocolo", motor.METODOS, PROTOCOLOS.get)
        st.caption("Cada conexão de entrada inclui um modelo na avaliação.")
    if tipo != "modelo":
        st.markdown("[Ver inspeção](#inspecao)")
    st.button("Remover bloco", on_click=remover, args=(no.id,), key=f"remover_{chave}")


def inspecionar(no, grafo):
    tipo, i = no["tipo"], no["id"]
    if tipo == "modelo":
        return
    with st.container(key="inspecao"):
        st.subheader(NOMES[tipo], anchor="inspecao")
        try:
            if tipo == "dados":
                paineis.resumo_da_base(fluxo.ler_base(no, ss.anexos))
                return
            execucao = ss.get("execucao")
            if tipo == "avaliar":
                planos = execucao.planos if execucao else fluxo.planejar(grafo, ss.anexos)
                tarefa = planos[i]
                st.caption(fluxo.rotulo(tarefa))
                paineis.particoes(tarefa)
                return
            nos, pais = fluxo.validar(grafo)
            if tipo == "preparar":
                origem = fluxo.unico(pais, i, "Ligue Dados à entrada da Preparação.")
                paineis.preparacao(fluxo.ler_base(nos[origem], ss.anexos), no["config"]["cenario"])
            else:
                origem = fluxo.unico(pais, i, "Ligue uma Avaliação à entrada de Resultados.")
                if not execucao or origem not in execucao.avaliacoes:
                    st.info("Execute o fluxo para calcular os resultados.")
                    return
                tarefa = execucao.planos[origem]
                st.caption(fluxo.rotulo(tarefa))
                paineis.resultados(execucao.avaliacoes[origem], tarefa)
        except fluxo.ErroFluxo as erro:
            st.info(str(erro))


def solicitar_execucao():
    ss.pop("aviso_conexao", None)
    ss.pedido = True


def executar(grafo):
    with st.spinner("Preparando as partições e treinando os modelos conectados…", show_time=True):
        try:
            ss.execucao = fluxo.executar(grafo, ss.anexos)
        except fluxo.ErroFluxo as erro:
            ss.falha = str(erro)
        else:
            for elo in grafo["conexoes"]:
                if elo["origem"] in ss.execucao.avaliacoes:
                    ss.selecao = elo["destino"]
                    break


def cabecalho():
    with st.container(key="cabecalho"):
        marca, novo, exemplo = st.columns([5.5, 1, 1.15], vertical_alignment="center", gap="small")
        logo = b64encode((IMAGENS / "logo_escuro.png").read_bytes()).decode("ascii")
        marca.html(f'<h1 class="marca"><img src="data:image/png;base64,{logo}" alt="VETOR">'
                   '<span>Laboratório Visual de IA</span></h1>')
        novo.button("Novo fluxo", on_click=substituir, width="stretch")
        exemplo.button("Abrir exemplo", on_click=substituir, args=(True,), width="stretch")


def main():
    st.set_page_config(page_title="VETOR · Laboratório Visual de IA", page_icon=str(IMAGENS / "icone.png"),
                       layout="wide")
    st.html(PASTA / "estilo.css")
    if "editor" not in ss:
        substituir(exemplo=True)
    cabecalho()
    with st.container(key="ferramentas", horizontal=True, vertical_alignment="center", gap="small"):
        st.caption("Adicionar bloco", width="content")
        for tipo, nome in NOMES.items():
            st.button(nome, key=f"adicionar_{tipo}", on_click=adicionar, args=(tipo,))
    with st.container(key="bancada"):
        canvas, painel = st.columns([4.65, 1.28], gap="small")
    with canvas:
        st.caption("Arraste os blocos. Para conectar, arraste da saída à entrada do próximo bloco.")
        retorno = streamlit_flow(
            f"vetor_{ss.tela}", ss.publicado, height=455, fit_view=True, min_zoom=0.2,
            allow_new_edges=True, get_node_on_click=True, get_edge_on_click=True,
            style={"background": "#181B1E", "border": "1px solid #343940", "borderRadius": 8},
        )
    receber_editor(retorno)

    grafo = desenho_editor(ss.editor)
    assinatura = fluxo.assinatura(grafo)
    if assinatura != ss.get("assinatura"):
        limpar_resultados()
        ss.assinatura = assinatura
    with painel.container(key="propriedades"):
        st.button("Executar fluxo", type="primary", width="stretch", on_click=solicitar_execucao)
        if ss.get("pedido"):
            limpar_resultados()
            executar(grafo)
            ss.pop("pedido", None)
        if falha := ss.get("falha"):
            st.error(falha)
        elif ss.get("execucao"):
            st.success("Execução concluída.")
        if aviso := ss.get("aviso_conexao"):
            st.warning(aviso)
        st.subheader("Propriedades")
        no = next((n for n in ss.editor.nodes if n.id == ss.selecao), None)
        if no:
            propriedades(no)
        elif any(e.id == ss.selecao for e in ss.editor.edges):
            st.caption("Conexão selecionada.")
            st.button("Remover conexão", on_click=remover, args=(ss.selecao,))
        else:
            st.caption("Selecione um bloco para configurar ou inspecionar sua saída.")
    if no:
        inspecionar(next(n for n in grafo["nos"] if n["id"] == no.id), grafo)


if __name__ == "__main__":
    main()
