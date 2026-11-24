"""Dados, modelos do Orange e avaliação do Projeto Integrador da UEG."""

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from Orange.data import ContinuousVariable, Domain, Table
from Orange.regression import LinearRegressionLearner, RandomForestRegressionLearner, TreeLearner
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import KFold, train_test_split


DADOS = Path(__file__).resolve().parent / "dados"
ORIGINAL = DADOS / "02_educacao.csv"
CODIGO = "codigo_escola"
INICIAL = "aprovacao_anos_iniciais_pct"
ALVO = "aprovacao_anos_finais_pct"
REDE = "dependencia_administrativa"
LOCALIZACAO = "localizacao"
PERFIL = ["R", "M", "P", "F"]
ENTRADAS = [INICIAL, *PERFIL]
VARIAVEIS = {"M1": [INICIAL], "M2": PERFIL, "M3": ENTRADAS, "M4": ENTRADAS, "M5": ENTRADAS}
REDES = ("Municipal", "Estadual", "Privada", "Federal")
LOCALIZACOES = ("Urbana", "Rural")
MUNICIPIO = "codigo_municipio"
MEDIO = "aprovacao_ensino_medio_pct"
COMPLETAS = "Cenário A · entradas completas"
AMPLIADA = "Cenário B · perfil ampliado"
ATRIBUTOS = {
    "ano": ("Ano de referência", "Contexto"),
    MUNICIPIO: ("Código do município", "Identificação"),
    "municipio": ("Nome do município", "Contexto"),
    CODIGO: ("Código único da escola", "Identificação"),
    "escola": ("Nome da escola", "Identificação"),
    LOCALIZACAO: ("Localização urbana ou rural", "Entrada de perfil"),
    REDE: ("Rede estadual, municipal, privada ou federal", "Entrada de perfil"),
    INICIAL: ("Aprovação dos anos iniciais do Ensino Fundamental (%)", "Entrada numérica"),
    MEDIO: ("Aprovação do Ensino Médio (%)", "Fora do modelo"),
    ALVO: ("Aprovação dos anos finais do Ensino Fundamental (%)", "Alvo"),
}
OBRIGATORIOS = set(ATRIBUTOS) - {MEDIO}
TESTE = "Treino e teste · 80/20"
SIMPLES = "Validação cruzada · 5 divisões"
ANINHADA = "Validação cruzada aninhada"
METODOS = (TESTE, SIMPLES, ANINHADA)
MEDIA = "Média do treino"
MEDIANA = "Mediana do treino"
SELECAO = "Seleção interna"


def importar_csv(conteudo):
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = conteudo.decode("cp1252")
        except UnicodeDecodeError:
            raise ValueError("Salve o CSV com codificação UTF-8 ou Windows-1252.") from None

    primeira_linha = texto.lstrip().split("\n", 1)[0]
    delimitador = ";" if primeira_linha.count(";") > primeira_linha.count(",") else ","
    try:
        # Ler o cabeçalho como primeira linha preserva nomes duplicados para validação.
        tabela = pd.read_csv(StringIO(texto), sep=delimitador, header=None, dtype=str,
                             keep_default_na=False, engine="python")
    except pd.errors.EmptyDataError as erro:
        raise ValueError("O CSV precisa de um cabeçalho com nomes de coluna únicos e preenchidos.") from erro
    except pd.errors.ParserError as erro:
        raise ValueError("CSV malformado. Confira as aspas, os separadores e o número de campos.") from erro
    colunas = tabela.iloc[0].str.strip()
    if colunas.eq("").any() or colunas.duplicated().any():
        raise ValueError("O CSV precisa de um cabeçalho com nomes de coluna únicos e preenchidos.")
    faltantes = OBRIGATORIOS - set(colunas)
    if faltantes:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(sorted(faltantes))}.")
    base = tabela.iloc[1:].set_axis(colunas.tolist(), axis=1)
    if base.empty:
        raise ValueError("O CSV precisa conter pelo menos um registro.")
    if base.isna().any(axis=None):
        raise ValueError("Cada linha do CSV deve ter o mesmo número de campos que o cabeçalho.")
    base = base.apply(lambda coluna: coluna.str.strip())
    for campo in (CODIGO, MUNICIPIO, "ano"):
        formato = r"[0-9]{4}" if campo == "ano" else r"[0-9]+"
        if not base[campo].str.fullmatch(formato).all():
            raise ValueError(f"A coluna {campo} precisa conter códigos numéricos válidos em todas as linhas.")
    if base[CODIGO].duplicated().any():
        raise ValueError("Cada código de escola deve aparecer uma única vez no CSV.")
    if base[["escola", "municipio"]].eq("").any().any():
        raise ValueError("Preencha os nomes das escolas e dos municípios.")

    for campo, categorias in ((LOCALIZACAO, LOCALIZACOES), (REDE, REDES)):
        padrao = {nome.casefold(): nome for nome in categorias}
        base[campo] = base[campo].str.casefold().map(padrao)
        if base[campo].isna().any():
            raise ValueError(f"Valores aceitos em {campo}: {', '.join(categorias)}.")

    for campo in [c for c in (INICIAL, ALVO, MEDIO) if c in base]:
        original = base[campo]
        taxa = pd.to_numeric(original.str.replace(",", ".", regex=False), errors="coerce")
        if (original.ne("") & ~taxa.between(0, 100)).any():
            raise ValueError(f"A coluna {campo} aceita números entre 0 e 100 e campos vazios.")
        base[campo] = taxa.astype(float)
    return base.replace("", None).set_index(CODIGO)


def preparar(base, cenario):
    obrigatorios = [ALVO, INICIAL] if cenario == COMPLETAS else [ALVO]
    colunas = [INICIAL, ALVO, LOCALIZACAO, REDE, MUNICIPIO, "municipio", "escola"]
    elegiveis = base[colunas].dropna(subset=obrigatorios)
    elegiveis["R"] = elegiveis[LOCALIZACAO].eq("Rural").astype(int)
    for indicador, rede in zip(("M", "P", "F"), ("Municipal", "Privada", "Federal")):
        elegiveis[indicador] = elegiveis[REDE].eq(rede).astype(int)
    sem_alvo = int(base[ALVO].isna().sum())
    return elegiveis, {
        "Total": len(base),
        "Elegíveis": len(elegiveis),
        "Sem taxa final": sem_alvo,
        "Sem taxa inicial": len(base) - sem_alvo - len(elegiveis),
    }

def criar_aprendiz(codigo):
    if codigo == "M4":
        return TreeLearner(binarize=True, min_samples_leaf=2, min_samples_split=5, max_depth=100)
    if codigo == "M5":
        return RandomForestRegressionLearner(
            n_estimators=10, random_state=0, min_samples_split=5, min_samples_leaf=1,
            max_features=1.0, max_depth=None, bootstrap=True,
        )
    return LinearRegressionLearner(fit_intercept=True)


def ajustar(codigo, treino):
    colunas = VARIAVEIS[codigo]
    dominio = Domain([ContinuousVariable(v) for v in colunas], ContinuousVariable(ALVO))
    tabela = Table.from_numpy(dominio, treino[colunas].to_numpy(float), treino[ALVO].to_numpy(float))
    return criar_aprendiz(codigo)(tabela)


def prever_linhas(modelo, codigo, linhas):
    # A tabela de treino tem alvo. A inferência recebe só as colunas explicativas.
    return modelo(linhas[VARIAVEIS[codigo]].to_numpy(float))


def calcular_metricas(observadas, previstas):
    variacao = len(observadas) > 1 and max(observadas) != min(observadas)
    return {
        "MAE": mean_absolute_error(observadas, previstas),
        "RMSE": root_mean_squared_error(observadas, previstas),
        "R²": r2_score(observadas, previstas) if variacao else None,
    }


@dataclass
class Plano:
    amostra: pd.DataFrame
    divisoes: list


@dataclass
class Resultado:
    ranking: pd.DataFrame
    referencias: pd.DataFrame
    previsoes: pd.DataFrame
    selecao_interna: pd.DataFrame
    municipios_em_comum: int


def particoes_academicas(cenario):
    try:
        tabela = pd.read_csv(DADOS / "particoes.csv", usecols=["cenario", "etapa", "ordem", CODIGO],
                             dtype={CODIGO: str, "ordem": int})
    except (OSError, ValueError) as erro:
        raise ValueError("Não foi possível ler o arquivo de partições acadêmicas.") from erro
    codigo = "B" if cenario == AMPLIADA else "A"
    linhas = tabela.loc[tabela["cenario"].eq(codigo)].sort_values("ordem")
    return {etapa: pd.Index(linhas.loc[linhas["etapa"].eq(etapa), CODIGO])
            for etapa in ("Treinamento", "Teste")}


def planejar(elegiveis, metodo, original, cenario):
    if metodo not in METODOS:
        raise ValueError("Escolha um método de avaliação válido.")
    if len(elegiveis) < 10:
        raise ValueError("São necessárias pelo menos 10 escolas elegíveis para executar a avaliação.")
    cruzada_historica = original and cenario == COMPLETAS and metodo == SIMPLES
    if original and (metodo == TESTE or cruzada_historica):
        particoes = particoes_academicas(cenario)
        codigos_treino, codigos_teste = particoes["Treinamento"], particoes["Teste"]
        codigos = codigos_treino.append(codigos_teste)
        tamanhos = (680, 170) if cenario == COMPLETAS else (1393, 349)
        if (len(codigos_treino), len(codigos_teste)) != tamanhos or (
            not codigos.is_unique or set(codigos) != set(elegiveis.index)
        ):
            raise ValueError("As partições acadêmicas divergem da base original preparada.")
        if metodo == TESTE:
            limite = len(codigos_treino)
            return Plano(elegiveis.loc[codigos], [(np.arange(limite), np.arange(limite, len(codigos)))])
        # A validação cruzada histórica usou apenas o treinamento da partição A.
        amostra = elegiveis.loc[codigos_treino]
    else:
        amostra = elegiveis.sort_index()
    if metodo == TESTE:
        tr, te = train_test_split(np.arange(len(amostra)), test_size=0.2, random_state=2026)
        divisoes = [(tr, te)]
    else:
        semente = 42 if metodo == SIMPLES else 2026
        divisoes = list(KFold(n_splits=5, shuffle=True, random_state=semente).split(amostra))
    return Plano(amostra, divisoes)


def avaliar_divisao(treino, avaliacao, modelos, referencias):
    if treino.index.intersection(avaliacao.index).size:
        raise ValueError("A mesma escola aparece no treinamento e na avaliação da divisão.")
    previstos = {}
    for nome in referencias:
        taxa = treino[ALVO].mean() if nome == MEDIA else treino[ALVO].median()
        previstos[nome] = np.full(len(avaliacao), taxa)
    previstos.update({m: prever_linhas(ajustar(m, treino), m, avaliacao) for m in modelos})
    return previstos


def selecionar_internamente(treino_externo, modelos, referencias, divisao):
    candidatos = [*referencias, *modelos]
    estimativas = {nome: np.empty(len(treino_externo)) for nome in candidatos}
    semente = 3026 + divisao
    grupos = KFold(n_splits=4, shuffle=True, random_state=semente)
    for indices_treino, indices_validacao in grupos.split(treino_externo):
        treino = treino_externo.iloc[indices_treino]
        validacao = treino_externo.iloc[indices_validacao]
        previsoes = avaliar_divisao(treino, validacao, modelos, referencias)
        for nome, valores in previsoes.items():
            estimativas[nome][indices_validacao] = valores
    erros = {nome: root_mean_squared_error(treino_externo[ALVO], valores)
             for nome, valores in estimativas.items()}
    # A ordem dos candidatos é o critério de desempate do protocolo.
    vencedor = min(erros, key=erros.get)
    return vencedor, {"Divisão externa": divisao, "Semente interna": semente, "Selecionado": vencedor, **erros}


def tabela_de_metricas(previsoes, candidatos):
    metricas = {nome: calcular_metricas(previsoes[ALVO], previsoes[nome]) for nome in candidatos}
    tabela = pd.DataFrame.from_dict(metricas, orient="index")
    return tabela.rename_axis("Modelo").sort_values("RMSE", kind="stable")


def executar_plano(plano, cenario, metodo, modelos):
    modelos = tuple(m for m in VARIAVEIS if m in modelos)
    if not modelos or (cenario == AMPLIADA and modelos != ("M2",)):
        raise ValueError("Selecione modelos compatíveis com o cenário.")
    aninhada = metodo == ANINHADA
    referencias = [MEDIA, MEDIANA]
    partes = []
    selecao = []
    municipios_em_comum = 0
    for numero, (indices_treino, indices_teste) in enumerate(plano.divisoes, 1):
        treino = plano.amostra.iloc[indices_treino]
        teste = plano.amostra.iloc[indices_teste]
        if aninhada:
            vencedor, registro = selecionar_internamente(treino, modelos, referencias, numero)
            selecao.append(registro)
        previstas = avaliar_divisao(treino, teste, modelos, referencias)
        if aninhada:
            previstas[SELECAO] = previstas[vencedor]
        colunas = ["escola", "municipio", MUNICIPIO, ALVO]
        partes.append(teste[colunas].assign(divisao=numero, **previstas))
        municipios_em_comum += int(teste[MUNICIPIO].isin(treino[MUNICIPIO]).sum())

    previsoes = pd.concat(partes, verify_integrity=True)
    ranking = tabela_de_metricas(previsoes, modelos)
    comparadores = tabela_de_metricas(previsoes, referencias + ([SELECAO] if aninhada else []))
    return Resultado(ranking, comparadores, previsoes, pd.DataFrame(selecao), municipios_em_comum)
