"""Exibição dos dados, métricas e estimativas na área de inspeção."""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import motor
from fluxo import MODELOS


MINIMOS_QUADRADOS = "Mínimos quadrados ordinários, com intercepto e sem regularização."
DETALHES = {
    "M1": (
        "Ajusta uma reta entre as duas taxas para isolar a associação com a taxa inicial.",
        "A inclinação é a mesma para todos os perfis. Pode extrapolar 0–100%.",
        MINIMOS_QUADRADOS,
    ),
    "M2": (
        "Estima a taxa usando localização e rede, inclusive em escolas sem taxa inicial no cenário B.",
        "Escolas com a mesma localização e rede recebem a mesma estimativa. Pode extrapolar 0–100%.",
        f"{MINIMOS_QUADRADOS} Urbana estadual é o perfil de referência.",
    ),
    "M3": (
        "Soma o intercepto e as contribuições das cinco entradas para testar o ganho ao incluir o perfil.",
        "As contribuições são aditivas e cada coeficiente depende das demais entradas. Pode extrapolar 0–100%.",
        MINIMOS_QUADRADOS,
    ),
    "M4": (
        "Representa interações por regras. Cada folha estima a média do alvo das escolas do treino que chegam à folha.",
        "Folhas com poucos exemplos podem ser instáveis.",
        "Árvore binária do Orange, mínimo 2 na folha, 5 para dividir, profundidade máxima 100.",
    ),
    "M5": (
        "Faz a média de dez árvores, reduzindo a influência de cada divisão individual.",
        "Uma previsão é mais difícil de explicar por uma única regra.",
        "Semente 0, amostragem com reposição, todas as entradas candidatas, mínimo 1 na folha, "
        "5 para dividir e profundidade sem limite explícito.",
    ),
}


def numero(valor, casas=2):
    return f"{valor:.{casas}f}".replace("-", "−").replace(".", ",")


def tabela(colunas, linhas):
    dados = pd.DataFrame(linhas, columns=colunas)
    st.html(dados.to_html(classes="dados", index=False, border=0, justify="left"))


SERIE = "#F7F8FA"
REGUA = "#A8ADB4"
AJUSTE_LARGURA = alt.AutoSizeParams(type="fit-x", contains="padding", resize=True)


def exibir_grafico(grafico, altura):
    visual = grafico.properties(height=altura, autosize=AJUSTE_LARGURA)
    st.altair_chart(visual.configure_axis(labelFontSize=12, titleFontSize=13), width="stretch")


def barras(dados, categoria, valor, unidade, ordem):
    eixo = alt.Axis(tickMinStep=1, tickCount=5) if unidade == "Escolas" else alt.Axis(tickCount=5)
    formato = "d" if unidade == "Escolas" else ".3f"
    return alt.Chart(dados).mark_bar(color=SERIE, cornerRadiusEnd=3).encode(
        x=alt.X(valor, type="quantitative", title=unidade, axis=eixo),
        y=alt.Y(categoria, type="nominal", sort=ordem, title=None, axis=alt.Axis(labelOverlap=False)),
        tooltip=[alt.Tooltip(categoria, type="nominal"),
                 alt.Tooltip(valor, type="quantitative", title=unidade, format=formato)],
    )


def frequencias(serie, categoria, titulo):
    dados = serie.value_counts().rename_axis(categoria).reset_index(name="Escolas")
    grafico = barras(dados, categoria, "Escolas", "Escolas", "-x").properties(title=titulo)
    exibir_grafico(grafico, max(90, len(dados) * 29))


def metricas(ranking, metrica):
    dados = ranking[[metrica]].dropna().reset_index().rename(columns={metrica: "valor"})
    if dados.empty:
        st.caption("R² indefinido porque todas as taxas observadas são iguais.")
        return
    unidade = metrica if metrica == "R²" else f"{metrica} (p.p.)"
    grafico = barras(dados, "Modelo", "valor", unidade, list(ranking.index))
    exibir_grafico(grafico, max(62, len(dados) * 26))


def observadas_e_estimadas(dados, modelo):
    pontos = dados[[motor.ALVO, modelo, "escola", "municipio"]].reset_index()
    taxas = pontos[[motor.ALVO, modelo]].to_numpy()
    limite = [float(taxas.min()), float(taxas.max())]
    if limite[0] == limite[1]:
        limite = [limite[0] - 1, limite[1] + 1]
    if len(pontos) > 3500:
        pontos = pontos.sample(3500, random_state=2026)
        st.caption("A dispersão exibe uma amostra fixa de 3.500 escolas. Métricas e erros usam todo o conjunto avaliado.")
    escala = alt.Scale(domain=limite, zero=False)
    diagonal = alt.Chart(pd.DataFrame({"observada": limite, "estimada": limite})).mark_line(
        color=REGUA, strokeDash=[6, 4], strokeWidth=2,
    ).encode(x=alt.X("observada:Q", scale=escala, title="Observada (%)"),
             y=alt.Y("estimada:Q", scale=escala, title="Estimada (%)"))
    grafico = alt.Chart(pontos).mark_circle(size=54, color=SERIE, opacity=0.58, clip=True).encode(
        x=alt.X(motor.ALVO, type="quantitative", title="Observada (%)", scale=escala,
                axis=alt.Axis(tickCount=5)),
        y=alt.Y(modelo, type="quantitative", title="Estimada (%)", scale=escala),
        tooltip=[
            alt.Tooltip("escola:N", title="Escola"), alt.Tooltip("municipio:N", title="Município"),
            alt.Tooltip(motor.CODIGO, type="nominal", title="Código"),
            alt.Tooltip(motor.ALVO, type="quantitative", title="Observada (%)", format=".2f"),
            alt.Tooltip(modelo, type="quantitative", title="Estimada (%)", format=".2f"),
        ],
    )
    exibir_grafico((diagonal + grafico).interactive(), 225)
    st.caption("A diagonal indica igualdade. Passe o cursor sobre um ponto para identificar a escola.")


def erros(residuos):
    contagens, bordas = np.histogram(residuos, bins=24)
    faixas = pd.DataFrame({"inicio": bordas[:-1], "fim": bordas[1:], "escolas": contagens})
    barras = alt.Chart(faixas).mark_bar(color=SERIE, binSpacing=1).encode(
        x=alt.X("inicio:Q", bin="binned", title="Estimada − observada (p.p.)", axis=alt.Axis(tickCount=5)),
        x2="fim:Q",
        y=alt.Y("escolas:Q", title="Escolas"),
        tooltip=[
            alt.Tooltip("inicio:Q", title="De (p.p.)", format=".2f"),
            alt.Tooltip("fim:Q", title="Até (p.p.)", format=".2f"),
            alt.Tooltip("escolas:Q", title="Escolas"),
        ],
    )
    zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(color=REGUA, strokeWidth=2).encode(x="zero:Q")
    exibir_grafico(barras + zero, 225)
    st.caption("Erros positivos indicam superestimativa. Erros negativos indicam subestimativa.")


def inteiro(n):
    return f"{n:,}".replace(",", ".")


def resumo_da_base(base):
    indicadores = {
        "Escolas": len(base), "Municípios": base[motor.MUNICIPIO].nunique(),
        "Atributos": len(base.columns) + 1, "Com taxa inicial": base[motor.INICIAL].count(),
    }
    with st.container(key="numeros_base"):
        for coluna, (rotulo, n) in zip(st.columns(len(indicadores)), indicadores.items()):
            coluna.metric(rotulo, inteiro(n))
    anos = sorted(base["ano"].unique())
    periodo = anos[0] if len(anos) == 1 else f"{anos[0]} a {anos[-1]}"
    st.caption(f"Referência {periodo} · {inteiro(int(base.isna().sum().sum()))} valores ausentes no total.")

    rede, cobertura = st.columns([1.15, 1])
    with rede:
        frequencias(base[motor.REDE], "Rede", "Rede administrativa")
    with cobertura:
        situacao = base[motor.INICIAL].notna().map({True: "Disponível", False: "Ausente"})
        frequencias(situacao, "Taxa inicial", "Cobertura da aprovação inicial")

    with st.expander("Amostra dos registros e dicionário de dados", expanded=True):
        st.caption("Primeiros registros do arquivo selecionado.")
        st.dataframe(base.head(8).reset_index(), hide_index=True, width="stretch")
        descricoes = []
        quadro = base.reset_index()
        for campo in quadro.columns:
            descricao, papel = motor.ATRIBUTOS.get(campo, ("Coluna adicional do CSV", "Fora do modelo"))
            descricoes.append((campo, descricao, papel, int(quadro[campo].isna().sum())))
        st.dataframe(
            pd.DataFrame(descricoes, columns=["Atributo", "Descrição", "Papel", "Ausentes"]),
            hide_index=True, width="stretch",
        )
    with st.expander("Estatísticas das taxas preenchidas"):
        taxas = [c for c in (motor.INICIAL, motor.ALVO, motor.MEDIO) if c in base]
        linhas = []
        for campo in taxas:
            serie = base[campo].dropna()
            valores = [serie.mean(), serie.median(), serie.min(), serie.max()]
            linhas.append([motor.ATRIBUTOS[campo][0], inteiro(len(serie)),
                           *(numero(v) if pd.notna(v) else "—" for v in valores)])
        tabela(["Taxa", "Preenchidas", "Média", "Mediana", "Mínimo", "Máximo"], linhas)


def preparacao(base, cenario):
    elegiveis, resumo = motor.preparar(base, cenario)
    excluidas = resumo["Total"] - resumo["Elegíveis"]
    blocos = [
        (resumo["Total"], "Escolas na base"), (resumo["Elegíveis"], "Elegíveis"),
        (excluidas, "Excluídas"),
    ]
    st.html(
        '<div class="fluxo-dados">'
        + "".join(f"<div><strong>{inteiro(n)}</strong><span>{rotulo}</span></div>" for n, rotulo in blocos)
        + "</div>"
    )
    st.caption(
        f"{inteiro(resumo['Sem taxa final'])} escolas excluídas por ausência do alvo. "
        f"{inteiro(resumo['Sem taxa inicial'])} excluídas adicionalmente por ausência da taxa inicial."
    )
    total_com_alvo = int(base[motor.ALVO].notna().sum())
    total_com_entradas = int(base[[motor.INICIAL, motor.ALVO]].notna().all(axis=1).sum())
    st.caption(f"O cenário A compara os cinco modelos nas {inteiro(total_com_entradas)} escolas com as duas taxas. "
               f"O cenário B avalia somente M2 nas {inteiro(total_com_alvo)} escolas com taxa final.")
    esquerda, direita = st.columns(2)
    with esquerda:
        st.markdown("**O que queremos estimar**")
        st.write("Aprovação nos anos finais do Ensino Fundamental, em porcentagem. Essa coluna é o alvo.")
        st.markdown("**Taxas ausentes**")
        st.write("Os campos ausentes seguem sem preenchimento. A preparação mantém os zeros informados na base.")
    with direita:
        st.markdown("**Como o perfil vira entrada numérica**")
        st.write("R = rural, M = municipal, P = privada e F = federal. Urbana estadual tem os quatro indicadores iguais a zero.")
        st.markdown("**Proteção contra vazamento**")
        st.write("O modelo recebe apenas as entradas autorizadas. O alvo é separado das entradas. Códigos, nomes, ano e Ensino Médio ficam como metadados da base.")
    if not elegiveis.empty:
        with st.expander("Comparar registro original e preparado"):
            posicao = st.number_input("Posição no conjunto elegível", 1, len(elegiveis), 1)
            registro = elegiveis.iloc[[posicao - 1]]
            st.caption(f"Escola {registro.index[0]} · {registro['escola'].iloc[0]}")
            categorias = [motor.LOCALIZACAO, motor.REDE, motor.INICIAL, motor.ALVO]
            st.dataframe(registro[categorias], hide_index=True, width="stretch")
            nomes = motor.ENTRADAS if cenario == motor.COMPLETAS else motor.PERFIL
            st.caption("Entradas disponíveis após a codificação")
            st.dataframe(registro[nomes], hide_index=True, width="stretch")


def detalhe_modelo(codigo):
    definicao, limite, configuracao = DETALHES[codigo]
    variaveis = motor.VARIAVEIS[codigo]
    entradas = []
    if motor.INICIAL in variaveis:
        entradas.append("Taxa inicial")
    if set(motor.PERFIL).intersection(variaveis):
        entradas.append("Localização e rede")
    st.write(definicao)
    for rotulo, texto in [("Entradas", " + ".join(entradas)), ("Limitação", limite),
                          ("Configuração", configuracao)]:
        st.markdown(f"**{rotulo}**  \n{texto}")


def tabela_metricas(quadro, ranking=False):
    colunas = ["Modelo", "MAE (p.p.)", "RMSE (p.p.)", "R²"]
    linhas = []
    for posicao, (nome, linha) in enumerate(quadro.iterrows(), 1):
        valores = [numero(valor, 3) if pd.notna(valor) else "—" for valor in linha]
        linhas.append((f"{posicao}. {nome}" if ranking else nome, *valores))
    tabela(colunas, linhas)


def melhores(ranking):
    for coluna, (criterio, rotulo) in zip(
        st.columns(3), (("RMSE", "Menor RMSE"), ("MAE", "Menor MAE"), ("R²", "Maior R²")),
    ):
        casos = ranking[criterio].dropna()
        if casos.empty:
            coluna.metric(rotulo, "Indefinido")
        else:
            valor = casos.max() if criterio == "R²" else casos.min()
            nomes = " / ".join(casos.index[casos.eq(valor)])
            coluna.metric(rotulo, nomes, help=f"{numero(valor, 4)}" + (" p.p." if criterio != "R²" else ""))


def erros_atuais(resultado, escolha, desvios):
    previsoes = resultado.previsoes
    st.markdown("**Escolas com os maiores erros absolutos**")
    maiores = previsoes[["escola", "municipio", "divisao", motor.ALVO, escolha]].assign(
        erro=desvios, absoluto=desvios.abs(),
    ).nlargest(10, "absoluto").reset_index()
    maiores.columns = ["Código", "Escola", "Município", "Divisão", "Observada (%)", "Estimada (%)",
                       "Erro (p.p.)", "Erro absoluto (p.p.)"]
    st.dataframe(maiores, hide_index=True, width="stretch")
    st.caption(
        f"{inteiro(resultado.municipios_em_comum)} das {inteiro(len(previsoes))} escolas avaliadas "
        "pertencem a municípios presentes no treino da respectiva divisão."
    )


def particoes(tarefa):
    plano = tarefa["plano"]
    linhas = [(n, len(treino), len(teste)) for n, (treino, teste) in enumerate(plano.divisoes, 1)]
    st.caption(tarefa["metodo"])
    tabela(["Divisão", "Treino", "Avaliação"], linhas)
    if tarefa["metodo"] == motor.ANINHADA:
        st.caption("Cada treino externo usa quatro divisões internas para selecionar pelo menor RMSE.")


def resultados(resultado, tarefa):
    ranking = resultado.ranking
    prognosticos = resultado.previsoes
    st.caption(f"Execução atual · {tarefa['metodo']} · {inteiro(len(prognosticos))} escolas avaliadas")
    resumo, diagnostico = st.tabs(["Comparação", "Diagnóstico por escola"])
    with resumo:
        with st.container(key="melhores"):
            melhores(ranking)
        esquerda, direita = st.columns([1, 1])
        with esquerda:
            st.markdown("**Ranking por RMSE**")
            tabela_metricas(ranking, ranking=True)
        with direita:
            metrica = st.radio("Métrica do gráfico", ["RMSE", "MAE", "R²"], horizontal=True)
            metricas(ranking, metrica)
        st.caption(
            "MAE é a média dos erros absolutos. RMSE é a raiz da média dos erros ao quadrado e pesa mais os erros grandes. "
            "Os dois usam pontos percentuais. R² compara o erro quadrático com o da média observada e pode ser negativo."
        )
        with st.expander("Referências estatísticas e partições"):
            tabela_metricas(resultado.referencias)
            st.caption("A média e a mediana usam apenas o alvo das escolas de treino da divisão.")
            particoes(tarefa)
            if not resultado.selecao_interna.empty:
                st.markdown("**Escolha nas divisões internas**")
                st.dataframe(resultado.selecao_interna, hide_index=True, width="stretch")
    with diagnostico:
        modelo = st.selectbox("Modelo para os gráficos", list(ranking.index))
        residuos = prognosticos[modelo] - prognosticos[motor.ALVO]
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Observada × estimada**")
            observadas_e_estimadas(prognosticos, modelo)
        with cols[1]:
            st.markdown("**Distribuição de erros**")
            erros(residuos)
        fora = int((~prognosticos[modelo].between(0, 100)).sum())
        baixas = residuos[prognosticos[motor.ALVO].lt(90)].abs()
        if fora:
            st.warning(f"{inteiro(fora)} estimativas de {modelo} fora de 0–100%. As métricas usam as saídas brutas.")
        if not baixas.empty:
            st.caption(f"Taxa observada abaixo de 90% · {inteiro(len(baixas))} escolas · MAE {numero(baixas.mean())} p.p.")
        erros_atuais(resultado, modelo, residuos)
    st.caption(
        "Na base UEG, a estimativa se refere ao mesmo ano dos dados, 2025. As taxas se concentram perto de 100%, "
        "e algumas escolas apresentam erros elevados. Modelos lineares podem estimar fora de 0–100%. "
        "Prever anos futuros ou demonstrar efeitos causais exigiria outras evidências."
    )
