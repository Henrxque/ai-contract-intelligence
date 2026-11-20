# AI Contract Intelligence

Estudo de caso de engenharia de dados: contratos PDF entram em um pipeline com extração, validação, persistência SQL, rastreabilidade e entrega para revisão humana.

[README em inglês](README.md) · [Estudo de caso](docs/CASE_STUDY.md) · [Arquitetura](docs/ARCHITECTURE.md) · [Operação](docs/RUNBOOK.md) · [Verificação](docs/VERIFICATION.md)

## Como apresentar no portfólio

O estudo de caso explica o problema e as decisões. O pipeline demonstra lote, dados brutos, tabelas normalizadas, qualidade e recuperação. A revisão individual permite conferir os campos e suas evidências.

- **Estudo de caso:** http://127.0.0.1:8000/case-study
- **Pipeline executável:** http://127.0.0.1:8000/pipeline
- **Revisão individual:** http://127.0.0.1:8000/

O SQLite registra documentos por hash, extrações por configuração, tentativas e resultados. Reenviar um lote concluído reutiliza resultados. Campos e evidências são gravados em uma transação; contratos com pendências ficam fora da view de dados aceitos.

Na avaliação local com oito contratos fictícios, 76 de 88 valores corresponderam às respostas esperadas (86,4%). Onze campos do documento em texto corrido ficaram ausentes, e uma condição de pagamento quebrada em linhas saiu incompleta, com alerta. Nenhum valor errado foi marcado como suportado nesse conjunto. **Esses números avaliam regras locais em exemplos de desenvolvimento; não medem LLM nem acurácia em contratos reais.**

## O que funciona

- Upload de PDF com texto selecionável.
- Extração de partes, datas, valor, moeda, pagamento e cláusulas.
- JSON tipado, com `null` para o que não foi identificado.
- Verificação de campos obrigatórios, formatos, datas, valores e trechos de origem.
- Estados `supported`, `missing`, `uncertain` e `invalid`.
- Painel para inspecionar evidências, páginas e alertas.
- Exportação JSON, CSV e Excel, preservando as pendências.
- Três contratos inteiramente fictícios para demonstração.

## Executar no Windows

Requer Python 3.11 ou superior.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Acesse **http://127.0.0.1:8000/case-study** e abra **Run the pipeline**. Execute **Process fictional batch** duas vezes para conferir a reutilização. A interface está em inglês para apresentação a clientes internacionais. Referência da API: **http://127.0.0.1:8000/docs**.

Também é possível executar pelo terminal:

```powershell
.venv\Scripts\python -m app.cli batch app/samples --synthetic --database data/demo.sqlite3
.venv\Scripts\python -m app.cli batch app/samples --synthetic --database data/demo.sqlite3
.venv\Scripts\python -m app.cli inspect --database data/demo.sqlite3
.venv\Scripts\python -m app.cli evaluate --output data/evaluation.json
```

O lote aceita até dez arquivos e 10 MB somados. O comando `retry RUN_ID --database data/demo.sqlite3` retoma execuções pendentes ou com falha, até três tentativas. A recuperação é local e explícita; não há agendador autônomo.

O modo **Local rules** funciona sem chave. Ele reconhece rótulos em inglês e português seguidos de dois-pontos na mesma linha. Não interpreta qualquer formato de contrato; valores quebrados em várias linhas podem ficar incompletos. Esse limite aparece na interface e no resultado.

## Ativar extração com IA

Copie `.env.example` para `.env`, adicione sua chave OpenAI, mantenha ou altere o modelo compatível e configure `ENABLE_OPENAI=true`. Reinicie o servidor. A interface habilitará **LLM extraction** e exigirá o reconhecimento de que o texto será enviado ao provedor. A chave fica no servidor; o uso da API é cobrado pelo provedor.

O código do adaptador está implementado e coberto por testes simulados. **Não foi executada uma chamada paga real ao provedor nesta verificação.** Os exemplos locais não usam LLM.

## Como demonstrar para um cliente

1. Execute **Northstar · Needs review**: mostre a data ausente e o pagamento ambíguo.
2. Clique em **Payment terms**: confira o trecho literal e a página de origem.
3. Abra **Review queue** e **JSON**: mostre como as falhas permanecem explícitas.
4. Exporte em Excel: confira as abas de campos, alertas e metadados.
5. Execute **Meridian** e **Atlas** para contrastar campos com checagens aprovadas e dados conflitantes.

“Supported” indica correspondência com o texto e aprovação nas checagens de formato. Não significa validade jurídica nem extração completa. Não há porcentagens de confiança inventadas.

## Testar

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pytest -q
```

## GitHub

O projeto inclui licença MIT, documentação, versões de dependências fixadas, exemplos fictícios e workflow de testes. A publicação precisa de uma conta autenticada no GitHub CLI:

```sh
gh auth login
git add .
git commit -m "Build evidence-backed contract intelligence portfolio app"
gh repo create ai-contract-intelligence --public --source=. --remote=origin --push
```

Não coloque chaves, documentos da Aon, código de empregadores ou contratos de clientes no repositório. O projeto foi construído com dados sintéticos e não depende de conteúdo profissional confidencial.

Não há OCR, autenticação ou edição manual. **O modo em lote salva PDFs, texto e resultados no SQLite local**, mediante consentimento na interface; o banco fica fora do Git. A revisão individual continua sem histórico persistido. Uploads também podem usar armazenamento temporário do framework. O aplicativo deve permanecer local até receber os controles necessários para um serviço público. Consulte o README principal para os limites completos.
