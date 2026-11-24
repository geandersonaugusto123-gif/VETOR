"""Verificações reproduzíveis do VETOR, com os dados e as bibliotecas do projeto."""
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
import argparse
import platform
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from Orange.regression import LinearRegressionLearner, RandomForestRegressionLearner, TreeLearner
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

import fluxo
import motor


class MotorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = motor.importar_csv(motor.ORIGINAL.read_bytes())
        cls.a, _ = motor.preparar(cls.base, motor.COMPLETAS)
        cls.b, _ = motor.preparar(cls.base, motor.AMPLIADA)

    def test_entrada_localizada_e_invalidos(self):
        original = self.base.iloc[:8].copy()
        dados = original.to_csv(sep=";", decimal=",").encode("cp1252")
        pd.testing.assert_frame_equal(motor.importar_csv(dados), original)
        linhas = original.to_csv().splitlines()
        header, primeira = linhas[:2]
        for dados, erro in (
            ("", "cabeçalho"),
            ("\n".join([header]), "pelo menos um"),
            ("\n".join([header.replace("escola,", "ano,"), primeira]), "cabeçalho"),
            ("\n".join([header, primeira.rsplit(",", 1)[0]]), "mesmo número"),
            ("\n".join([header, primeira + ",demais"]), "CSV malformado"),
            ("\n".join([header, primeira, primeira]), "única vez"),
            (original.assign(**{motor.ALVO: "NaN"}).to_csv(), "entre 0 e 100"),
        ):
            with self.subTest(dados=dados[:30]), self.assertRaisesRegex(ValueError, erro):
                motor.importar_csv(dados.encode())

    def test_ausencia_zero_e_separacao_de_cenarios(self):
        original = self.base.iloc[:4].copy()
        original[motor.INICIAL] = [np.nan, 0.0, np.nan, 100.0]
        original[motor.ALVO] = [0.0, 50.0, np.nan, np.nan]
        base = motor.importar_csv(original.to_csv().encode())
        a, resumo_a = motor.preparar(base, motor.COMPLETAS)
        b, resumo_b = motor.preparar(base, motor.AMPLIADA)
        self.assertEqual(a[motor.INICIAL].tolist(), [0.0])
        self.assertEqual(b[motor.ALVO].tolist(), [0.0, 50.0])
        self.assertEqual(resumo_a, {"Total": 4, "Elegíveis": 1, "Sem taxa final": 2, "Sem taxa inicial": 1})
        self.assertEqual(resumo_b, {"Total": 4, "Elegíveis": 2, "Sem taxa final": 2, "Sem taxa inicial": 0})

    def test_recusa_particao_academica_corrompida_antes_do_ajuste(self):
        particoes = motor.particoes_academicas(motor.COMPLETAS)
        treino, teste = particoes["Treinamento"], particoes["Teste"]
        for divergencia in (
            {"Treinamento": treino[1:], "Teste": teste.insert(0, treino[0])},
            {"Treinamento": treino, "Teste": teste[1:].insert(0, treino[0])},
        ):
            with patch("motor.particoes_academicas", return_value=divergencia):
                for metodo in (motor.TESTE, motor.SIMPLES):
                    with self.subTest(metodo=metodo), self.assertRaisesRegex(ValueError, "divergem"):
                        motor.planejar(self.a, metodo, True, motor.COMPLETAS)

        with TemporaryDirectory() as pasta, patch("motor.DADOS", Path(pasta)):
            with self.assertRaisesRegex(ValueError, "Não foi possível"):
                motor.particoes_academicas(motor.COMPLETAS)
            Path(pasta, "particoes.csv").write_text("cenario,etapa\nA,Teste\n")
            with self.assertRaisesRegex(ValueError, "Não foi possível"):
                motor.particoes_academicas(motor.COMPLETAS)

    def test_divisoes_reproduziveis_disjuntas_e_cobertura(self):
        casos = [
            (self.a, motor.COMPLETAS, motor.TESTE, True, 1, 680, 170, 170),
            (self.a, motor.COMPLETAS, motor.SIMPLES, True, 5, 544, 136, 680),
            (self.a, motor.COMPLETAS, motor.ANINHADA, True, 5, 680, 170, 850),
            (self.b, motor.AMPLIADA, motor.TESTE, True, 1, 1393, 349, 349),
            (self.a, motor.COMPLETAS, motor.TESTE, False, 1, 680, 170, 170),
        ]
        for dados, cenario, metodo, original, quantidade, n_treino, n_teste, cobertura in casos:
            with self.subTest(cenario=cenario, metodo=metodo, original=original):
                plano = motor.planejar(dados, metodo, original, cenario)
                repeticao = motor.planejar(dados, metodo, original, cenario)
                pd.testing.assert_index_equal(plano.amostra.index, repeticao.amostra.index)
                self.assertEqual(len(plano.divisoes), quantidade)
                ids_avaliados = []
                for (it, iv), (it2, iv2) in zip(plano.divisoes, repeticao.divisoes, strict=True):
                    self.assertEqual((len(it), len(iv)), (n_treino, n_teste))
                    np.testing.assert_array_equal(it, it2)
                    np.testing.assert_array_equal(iv, iv2)
                    treino = plano.amostra.iloc[it].index
                    teste = plano.amostra.iloc[iv].index
                    self.assertTrue(treino.intersection(teste).empty)
                    ids_avaliados.extend(teste)
                self.assertEqual(len(ids_avaliados), cobertura)
                self.assertEqual(len(set(ids_avaliados)), cobertura)
                if original and metodo == motor.SIMPLES:
                    teste_original = motor.particoes_academicas(cenario)["Teste"]
                    self.assertTrue(pd.Index(ids_avaliados).intersection(teste_original).empty)

    def test_metricas_recalculadas_e_cobertura_b(self):
        funcoes = {"MAE": mean_absolute_error, "RMSE": root_mean_squared_error, "R²": r2_score}
        for cenario, dados, metodo, modelos in (
            (motor.COMPLETAS, self.a, motor.TESTE, motor.VARIAVEIS),
            (motor.COMPLETAS, self.a, motor.SIMPLES, motor.VARIAVEIS),
            (motor.COMPLETAS, self.a, motor.ANINHADA, motor.VARIAVEIS),
            (motor.AMPLIADA, self.b, motor.TESTE, ("M2",)),
        ):
            with self.subTest(cenario=cenario, metodo=metodo):
                plano = motor.planejar(dados, metodo, True, cenario)
                resultado = motor.executar_plano(plano, cenario, metodo, modelos)
                observadas = resultado.previsoes[motor.ALVO]
                self.assertIn(motor.MEDIA, resultado.referencias.index)
                self.assertIn(motor.MEDIANA, resultado.referencias.index)
                if cenario == motor.AMPLIADA:
                    mediana = resultado.referencias.loc[motor.MEDIANA]
                    self.assertEqual(len(observadas), 349)
                    self.assertAlmostEqual(mediana["MAE"], 1.408, places=3)
                    self.assertAlmostEqual(mediana["RMSE"], 3.154, places=3)
                    self.assertAlmostEqual(mediana["R²"], -0.249, places=3)
                for tabela in (resultado.ranking, resultado.referencias):
                    for modelo, linha in tabela.iterrows():
                        for medida, calcular in funcoes.items():
                            self.assertEqual(linha[medida], calcular(observadas, resultado.previsoes[modelo]))
                for it, iv in plano.divisoes:
                    treino = plano.amostra.iloc[it][motor.ALVO]
                    previsoes = resultado.previsoes.loc[plano.amostra.iloc[iv].index]
                    self.assertTrue(previsoes[motor.MEDIA].eq(treino.mean()).all())
                    self.assertTrue(previsoes[motor.MEDIANA].eq(treino.median()).all())

    def test_ajusta_os_cinco_modelos_orange_em_680_escolas(self):
        classes = [LinearRegressionLearner, LinearRegressionLearner, LinearRegressionLearner,
                   TreeLearner, RandomForestRegressionLearner]
        particoes = motor.particoes_academicas(motor.COMPLETAS)
        treino, teste = self.a.loc[particoes["Treinamento"]], self.a.loc[particoes["Teste"]]
        for codigo, classe in zip(motor.VARIAVEIS, classes, strict=True):
            with self.subTest(codigo=codigo):
                self.assertIs(type(motor.criar_aprendiz(codigo)), classe)
                com_alvo = motor.ajustar(codigo, treino)
                self.assertEqual([variavel.name for variavel in com_alvo.domain.attributes],
                                 motor.VARIAVEIS[codigo])
                np.testing.assert_array_equal(
                    motor.prever_linhas(com_alvo, codigo, teste),
                    motor.prever_linhas(com_alvo, codigo, teste.drop(columns=motor.ALVO)),
                )


class ValidadorTest(unittest.TestCase):
    def test_resultados_ausentes_bloqueiam_treino(self):
        grafo = fluxo.exemplo()
        grafo["conexoes"].remove({"origem": "avaliador", "destino": "resultados"})
        # A inspeção do bloco de Avaliação ainda consegue mostrar as divisões.
        self.assertIn("avaliador", fluxo.planejar(grafo, {}))
        with patch("motor.ajustar") as ajuste:
            with self.assertRaisesRegex(fluxo.ErroFluxo, "bloco de Resultados"):
                fluxo.executar(grafo, {})
            ajuste.assert_not_called()

    def test_portas_incompativeis_e_segunda_entrada(self):
        grafo = fluxo.exemplo()
        grafo["conexoes"].append({"origem": "base", "destino": "avaliador"})
        with self.assertRaisesRegex(fluxo.ErroFluxo, "Ligue Modelos"):
            fluxo.validar(grafo)
        grafo["conexoes"].pop()
        segunda_base = deepcopy(grafo["nos"][0])
        segunda_base["id"] = "outra_base"
        grafo["nos"].append(segunda_base)
        grafo["conexoes"].append({"origem": "outra_base", "destino": "preparo"})
        with self.assertRaisesRegex(fluxo.ErroFluxo, "única entrada"):
            fluxo.validar(grafo)

    def test_base_em_sessao_reutiliza_tabela_validada(self):
        base = motor.importar_csv(motor.ORIGINAL.read_bytes())
        no = {"id": "base", "config": {"fonte": "csv"}}
        with patch("motor.importar_csv") as importar:
            self.assertIs(fluxo.ler_base(no, {"base": ("validado.csv", base)}), base)
            importar.assert_not_called()
        with self.assertRaisesRegex(fluxo.ErroFluxo, "Carregue um arquivo"):
            fluxo.ler_base(no, {})

    def test_modelos_conectados_e_reconexao(self):
        grafo = fluxo.exemplo()
        aresta = {"origem": "m5", "destino": "avaliador"}
        grafo["conexoes"].remove(aresta)
        with patch("motor.ajustar", wraps=motor.ajustar) as ajuste:
            resultado = fluxo.executar(grafo, {}).avaliacoes["avaliador"]
            self.assertEqual({chamada.args[0] for chamada in ajuste.call_args_list},
                             {"M1", "M2", "M3", "M4"})
        self.assertNotIn("M5", resultado.ranking.index)
        grafo["conexoes"].append(aresta)
        self.assertEqual(set(fluxo.executar(grafo, {}).avaliacoes["avaliador"].ranking.index),
                         set(motor.VARIAVEIS))

    def test_cenario_b_aceita_apenas_m2(self):
        grafo = fluxo.exemplo()
        next(no for no in grafo["nos"] if no["id"] == "preparo")["config"]["cenario"] = motor.AMPLIADA
        with self.assertRaisesRegex(fluxo.ErroFluxo, "somente M2"):
            fluxo.executar(grafo, {})
        grafo["conexoes"] = [c for c in grafo["conexoes"]
                             if c["destino"] != "avaliador" or c["origem"] == "m2"]
        resultado = fluxo.executar(grafo, {}).avaliacoes["avaliador"]
        self.assertEqual(list(resultado.ranking.index), ["M2"])
        self.assertEqual(len(resultado.previsoes), 349)


def plano_academico(base, cenario, metodo):
    escolas, _ = motor.preparar(base, cenario)
    return motor.planejar(escolas, metodo, True, cenario)


class PesquisaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = motor.importar_csv(motor.ORIGINAL.read_bytes())
        cls.aninhado = plano_academico(cls.base, motor.COMPLETAS, motor.ANINHADA)

    def test_base_original_contagens_codificacao_e_atributos(self):
        base = self.base
        self.assertEqual((len(base), base[motor.MUNICIPIO].nunique(), len(base.columns) + 1), (1742, 246, 10))
        self.assertTrue(base.index.is_unique)
        self.assertEqual([base[c].isna().sum() for c in (motor.INICIAL, motor.ALVO, motor.MEDIO)], [892, 0, 826])
        for c in (motor.INICIAL, motor.ALVO, motor.MEDIO):
            self.assertTrue(base[c].dropna().between(0, 100).all())
        self.assertEqual(base.index[base[motor.INICIAL].eq(0)].tolist(), ["52069745"])
        self.assertEqual(base.index[base[motor.ALVO].eq(0)].tolist(), ["52099067"])
        a, _ = motor.preparar(base, motor.COMPLETAS)
        self.assertEqual(a.loc["52007120", motor.PERFIL].to_list(), [1, 1, 0, 0])
        for campo, coluna, valor in (("R", motor.LOCALIZACAO, "Rural"), ("M", motor.REDE, "Municipal"),
                                     ("P", motor.REDE, "Privada"), ("F", motor.REDE, "Federal")):
            np.testing.assert_array_equal(a[campo], a[coluna].eq(valor).astype(int))
        self.assertEqual(motor.VARIAVEIS, {"M1": [motor.INICIAL], "M2": ["R", "M", "P", "F"],
            **{m: [motor.INICIAL, "R", "M", "P", "F"] for m in ("M3", "M4", "M5")}})

    def test_metricas_em_caso_conhecido(self):
        self.assertEqual(motor.calcular_metricas([90, 94], [92, 96]), {"MAE": 2, "RMSE": 2, "R²": 0})
        self.assertIsNone(motor.calcular_metricas([2, 2], [1, 1])["R²"])

    def test_reprodutibilidade_da_floresta(self):
        plano = plano_academico(self.base, motor.COMPLETAS, motor.TESTE)
        treino, teste = (plano.amostra.iloc[i] for i in plano.divisoes[0])
        a = motor.ajustar("M5", treino)
        b = motor.ajustar("M5", treino)
        np.testing.assert_array_equal(motor.prever_linhas(a, "M5", teste), motor.prever_linhas(b, "M5", teste))

    def test_respostas_externas_nao_participam_da_selecao(self):
        plano = self.aninhado
        original = motor.executar_plano(plano, motor.COMPLETAS, motor.ANINHADA, motor.VARIAVEIS)
        ids = plano.amostra.iloc[plano.divisoes[0][1]].index
        alterada = plano.amostra.copy()
        alterada.loc[ids, motor.ALVO] = 0
        outro = motor.executar_plano(motor.Plano(alterada, plano.divisoes), motor.COMPLETAS,
                                     motor.ANINHADA, motor.VARIAVEIS)
        pd.testing.assert_series_equal(original.selecao_interna.iloc[0], outro.selecao_interna.iloc[0])
        colunas = [*motor.VARIAVEIS, motor.SELECAO]
        pd.testing.assert_frame_equal(original.previsoes.loc[ids, colunas], outro.previsoes.loc[ids, colunas])

    def test_casos_do_relatorio_e_lideres_por_rmse(self):
        a = executar_avaliacao(self.base, motor.COMPLETAS, motor.TESTE, motor.VARIAVEIS)
        c = executar_avaliacao(self.base, motor.COMPLETAS, motor.SIMPLES, motor.VARIAVEIS)
        n = executar_avaliacao(self.base, motor.COMPLETAS, motor.ANINHADA, motor.VARIAVEIS)
        b = executar_avaliacao(self.base, motor.AMPLIADA, motor.TESTE, ("M2",))
        for r, lider, rmse, casos in ((a, "M3", 3.221, 170), (c, "M4", 3.211, 680),
                                      (n, "M5", 3.491, 850), (b, "M2", 2.721, 349)):
            self.assertEqual(len(r.previsoes), casos)
            self.assertEqual(r.ranking.index[0], lider)
            self.assertAlmostEqual(r.ranking.loc[lider, "RMSE"], rmse, places=3)
        self.assertEqual(list(n.selecao_interna["Selecionado"]), ["M5", "M3", "M3", "M5", "M5"])
        self.assertAlmostEqual(n.referencias.loc[motor.SELECAO, "RMSE"], 3.941, places=3)
        for codigo, observada, estimada in (("52007120", 100.0, 98.7886), ("52053253", 81.3, 99.1269)):
            self.assertEqual(a.previsoes.loc[codigo, motor.ALVO], observada)
            self.assertAlmostEqual(a.previsoes.loc[codigo, "M3"], estimada, places=4)


def executar_avaliacao(base, cenario, metodo, modelos):
    plano = plano_academico(base, cenario, metodo)
    return motor.executar_plano(plano, cenario, metodo, modelos)


def exportar_resultados(destino):
    """Reexecuta o motor com Orange3 e grava as fontes numéricas do relatório."""
    destino.mkdir(parents=True, exist_ok=True)
    base = motor.importar_csv(motor.ORIGINAL.read_bytes())
    metricas = []
    for arquivo, nome, cenario, metodo, modelos in (
        ("teste_80_20.csv", "80/20 A", motor.COMPLETAS, motor.TESTE, motor.VARIAVEIS),
        ("validacao_cruzada.csv", "Cruzada A", motor.COMPLETAS, motor.SIMPLES, motor.VARIAVEIS),
        ("validacao_aninhada.csv", "Aninhada A", motor.COMPLETAS, motor.ANINHADA, motor.VARIAVEIS),
        ("cenario_b.csv", "80/20 B", motor.AMPLIADA, motor.TESTE, ("M2",)),
    ):
        r = executar_avaliacao(base, cenario, metodo, modelos)
        resumo = pd.concat([r.ranking, r.referencias]).reset_index().assign(protocolo=nome)
        metricas.append(resumo)
        previsoes = r.previsoes.reset_index().assign(protocolo=nome)
        campos = ["protocolo", "divisao", "codigo_escola", "escola", "municipio", motor.ALVO]
        if metodo == motor.ANINHADA:
            r.selecao_interna.to_csv(destino / "selecao.csv", index=False)
            previsoes["escolha_interna"] = previsoes["divisao"].map(
                r.selecao_interna.set_index("Divisão externa")["Selecionado"]
            )
            campos.append("escolha_interna")
        por_modelo = previsoes.melt(
            id_vars=campos, value_vars=resumo["Modelo"],
            var_name="modelo", value_name="taxa_estimada",
        ).rename(columns={motor.ALVO: "taxa_observada"})
        por_modelo.to_csv(destino / arquivo, index=False)
    pd.concat(metricas, ignore_index=True).to_csv(destino / "metricas.csv", index=False)

    plano = plano_academico(base, motor.COMPLETAS, motor.TESTE)
    treino, teste = (plano.amostra.iloc[i] for i in plano.divisoes[0])
    sensibilidade = []
    for caso, amostra in (("M3 completo", treino), ("M3 sem a escola 52069745", treino.drop("52069745"))):
        modelo = motor.ajustar("M3", amostra)
        previstas = motor.prever_linhas(modelo, "M3", teste)
        sensibilidade.append(pd.DataFrame({
            "protocolo": "Sensibilidade de A", "modelo": "M3", "ajuste": caso,
            "divisao": 1, "codigo_escola": teste.index, "taxa_observada": teste[motor.ALVO].to_numpy(),
            "taxa_estimada": previstas, "treino": len(amostra),
            "intercepto": modelo.skl_model.intercept_, "coef_taxa_inicial": modelo.skl_model.coef_[0],
        }))
    pd.concat(sensibilidade, ignore_index=True).to_csv(destino / "sensibilidade.csv", index=False)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--exportar", type=Path, help="Pasta para as previsões e métricas recalculadas.")
    args = cli.parse_args()
    print(platform.platform(), f"| Python {platform.python_version()}", flush=True)
    for requirement in Path(__file__).with_name("requirements.txt").read_text().splitlines():
        nome = requirement.split("==")[0]
        print(f"{nome}=={version(nome)}", flush=True)
    print("SHA-256 do CSV:", sha256(motor.ORIGINAL.read_bytes()).hexdigest(), flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    total = suite.countTestCases()
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    reprovados = len({getattr(teste, "test_case", teste).id()
                      for teste, _ in resultado.failures + resultado.errors})
    nao_executados = total - resultado.testsRun + len(resultado.skipped)
    print(f"Aprovados: {total - reprovados - nao_executados} | Reprovados: {reprovados} | "
          f"Não executados: {nao_executados}", flush=True)
    if not resultado.wasSuccessful():
        raise SystemExit(1)
    if args.exportar:
        exportar_resultados(args.exportar)
