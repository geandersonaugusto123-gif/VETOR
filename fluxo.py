"""Transforma nós e conexões em experimentos que o motor consegue executar."""

from dataclasses import dataclass
from functools import cache

import motor

MODELOS = {
    "M1": "Regressão linear simples",
    "M2": "Regressão pelo perfil",
    "M3": "Regressão linear múltipla",
    "M4": "Árvore de regressão",
    "M5": "Random Forest",
}
ENTRADAS = dict(dados=None, preparar="dados", modelo="preparar", avaliar="modelo", resultados="avaliar")
TITULOS = dict(dados="Dados", preparar="Preparação", modelo="Modelos", avaliar="Avaliação", resultados="Resultados")
COLUNAS = dict(dados=0, preparar=182, modelo=364, avaliar=550, resultados=735)
PADROES = {
    "dados": {"fonte": "ueg"},
    "preparar": {"cenario": motor.COMPLETAS},
    "modelo": {"codigo": "M3"},
    "avaliar": {"metodo": motor.TESTE},
    "resultados": {},
}
OPCOES = dict(fonte=("ueg", "csv"), cenario=(motor.COMPLETAS, motor.AMPLIADA),
              codigo=tuple(MODELOS), metodo=motor.METODOS)


class ErroFluxo(ValueError):
    """Mensagem de validação para apresentar na interface."""


@dataclass
class Execucao:
    avaliacoes: dict
    planos: dict


def exemplo():
    blocos = [("base", "dados", 208, {}), ("preparo", "preparar", 208, {})]
    blocos += [(codigo.lower(), "modelo", 32 + 88 * linha, {"codigo": codigo})
               for linha, codigo in enumerate(MODELOS)]
    blocos += [("avaliador", "avaliar", 208, {}), ("resultados", "resultados", 208, {})]
    pares = [("base", "preparo"), ("avaliador", "resultados")]
    for codigo in MODELOS:
        pares.extend([("preparo", codigo.lower()), (codigo.lower(), "avaliador")])
    return {
        "nos": [{"id": i, "tipo": t, "x": COLUNAS[t], "y": y, "config": c} for i, t, y, c in blocos],
        "conexoes": [{"origem": a, "destino": b} for a, b in pares],
    }


def editar_config(tipo, config):
    padrao = PADROES[tipo]
    valores = {**padrao, **config}
    if valores.keys() != padrao.keys() or any(v not in OPCOES[c] for c, v in valores.items()):
        raise ErroFluxo(f"Configuração inválida em {TITULOS[tipo]}.")
    return valores


def validar(grafo):
    nos = {}
    for no in grafo["nos"]:
        identificador, tipo = no["id"], no["tipo"]
        if identificador in nos or tipo not in ENTRADAS:
            raise ErroFluxo("O fluxo contém um componente desconhecido ou duplicado.")
        nos[identificador] = {**no, "config": editar_config(tipo, no["config"])}
    pais = {i: [] for i in nos}
    for elo in grafo["conexoes"]:
        origem, destino = elo["origem"], elo["destino"]
        if origem not in nos or destino not in nos:
            raise ErroFluxo("Conecte dois componentes existentes.")
        if origem in pais[destino]:
            raise ErroFluxo("Essa conexão já existe.")
        tipo = nos[destino]["tipo"]
        recebido = ENTRADAS[tipo]
        # As portas seguem uma ordem fixa de tipos, portanto excluem ciclos.
        if nos[origem]["tipo"] != recebido:
            instrucao = f"Ligue {TITULOS[recebido]} à entrada de {TITULOS[tipo]}." if recebido else ""
            raise ErroFluxo(f"Conexão incompatível com {TITULOS[tipo]}. {instrucao}".rstrip())
        if tipo != "avaliar" and pais[destino]:
            raise ErroFluxo(f"{TITULOS[tipo]} aceita uma única entrada.")
        pais[destino].append(origem)
    return nos, pais


def assinatura(grafo):
    nos = sorted((n["id"], n["tipo"], dict(n["config"])) for n in grafo["nos"])
    elos = sorted((e["origem"], e["destino"]) for e in grafo["conexoes"])
    return nos, elos


def unico(pais, no, mensagem):
    if not pais[no]:
        raise ErroFluxo(mensagem)
    return pais[no][0]


def rotulo(tarefa):
    if not tarefa["original"]:
        return "Exploratório · CSV importado"
    if tarefa["cenario"] == motor.AMPLIADA:
        return "Acadêmico · cenário B" if tarefa["metodo"] == motor.TESTE else "Exploratório · cenário B"
    if set(tarefa["codigos"]) != set(MODELOS):
        return "Partições acadêmicas · seleção parcial de modelos"
    return "Acadêmico · cenário A"


@cache
def ler_base_original():
    try:
        return motor.importar_csv(motor.ORIGINAL.read_bytes())
    except (OSError, ValueError) as erro:
        raise ErroFluxo(f"Falha ao carregar a base original. {erro}") from erro


def ler_base(no, anexos):
    if no["config"]["fonte"] == "ueg":
        return ler_base_original()
    if no["id"] not in anexos:
        raise ErroFluxo("Carregue um arquivo no componente Dados.")
    return anexos[no["id"]][1]


def planejar(grafo, anexos):
    nos, pais = validar(grafo)
    avaliadores = [i for i, no in nos.items() if no["tipo"] == "avaliar"]
    if not avaliadores:
        raise ErroFluxo("Adicione uma Avaliação e conecte pelo menos um modelo.")
    preparados, tarefas = {}, {}
    for aid in avaliadores:
        modelos = pais[aid]
        if not modelos:
            raise ErroFluxo("Conecte pelo menos um modelo à Avaliação.")
        preparos = {unico(pais, i, "Ligue a Preparação à entrada do modelo.") for i in modelos}
        if len(preparos) != 1:
            raise ErroFluxo("Use a mesma Preparação para os modelos de uma avaliação.")
        pid = preparos.pop()
        fonte = nos[unico(pais, pid, "Ligue Dados à entrada da Preparação.")]
        cenario = nos[pid]["config"]["cenario"]
        codigos = [nos[i]["config"]["codigo"] for i in modelos]
        if len(set(codigos)) != len(modelos):
            raise ErroFluxo("Selecione algoritmos distintos neste avaliador.")
        if cenario == motor.AMPLIADA and codigos != ["M2"]:
            raise ErroFluxo("O cenário B avalia somente M2. Para comparar os demais, use o cenário A.")
        metodo = nos[aid]["config"]["metodo"]
        original = fonte["config"]["fonte"] == "ueg"
        try:
            if pid not in preparados:
                preparados[pid], _ = motor.preparar(ler_base(fonte, anexos), cenario)
            plano = motor.planejar(preparados[pid], metodo, original, cenario)
        except ValueError as erro:
            raise ErroFluxo(str(erro)) from erro
        tarefas[aid] = dict(plano=plano, metodo=metodo, cenario=cenario, original=original, codigos=codigos)
    return tarefas


def executar(grafo, anexos):
    tarefas = planejar(grafo, anexos)
    if tarefas.keys() - {elo["origem"] for elo in grafo["conexoes"]}:
        raise ErroFluxo("Ligue cada Avaliação a um bloco de Resultados antes de executar.")
    avaliacoes = {}
    for aid, tarefa in tarefas.items():
        try:
            avaliacoes[aid] = motor.executar_plano(
                tarefa["plano"], tarefa["cenario"], tarefa["metodo"], tarefa["codigos"],
            )
        except (ValueError, RuntimeError) as erro:
            raise ErroFluxo(str(erro)) from erro
    return Execucao(avaliacoes, tarefas)
