# Automação de relatórios de hotéis

Aplicativo desktop para importar relatórios de hotéis a partir dos sistemas
Desbravador Web e Queops para arquivos Excel 97-2003 (`.xls`) e PDF. A interface
permite manter perfis de hotéis, escolher quais hotéis ativos importar e
acompanhar o resultado de cada relatório.

> **Sistemas disponíveis:** Desbravador Web e Queops. Perfis AmerisConnect
> aparecem identificados como indisponíveis; esse coletor ainda não foi
> implementado. A falha de um perfil indisponível não impede a tentativa dos
> demais hotéis.

## Índice

- [Requisitos](#requisitos)
- [Instalação e execução](#instalação-e-execução)
- [Uso da interface](#uso-da-interface)
- [Cadastro e configuração](#cadastro-e-configuração)
- [Fluxo de importação](#fluxo-de-importação)
- [Coletor Desbravador Web](#coletor-desbravador-web)
- [Coletor Queops](#coletor-queops)
- [Arquivos, períodos e logs](#arquivos-períodos-e-logs)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)
- [Segurança e arquivos locais](#segurança-e-arquivos-locais)

## Requisitos

- Windows com Python instalado.
- Dependências de `requirements.txt`.
- Microsoft Excel instalado no Windows. O Excel e o suporte COM do `pywin32`
  são usados para criar, ajustar e validar os arquivos `.xls` do Desbravador.
- Google Chrome instalado para o Desbravador Web. A automação abre o Chrome
  visível e usa um perfil persistente exclusivo por hotel.
- Queops instalado e acessível em uma sessão interativa do Windows.
- Para o Queops, o atalho `PontalMundai.lnk` deve estar na Área de Trabalho,
  exceto quando o Queops já estiver aberto.
- Permissão de leitura e gravação nas pastas de configuração e de saída.

As dependências Python estão declaradas em `requirements.txt`: Playwright,
`pywin32` e `pywinauto`. O arquivo não fixa versões.

## Instalação e execução

Abra o PowerShell na pasta do projeto.

### Criar o ambiente virtual (se ainda não existir)

```powershell
python -m venv .venv
```

### Instalar ou atualizar as dependências

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Iniciar o aplicativo

```powershell
.\.venv\Scripts\python.exe app.py
```

O programa abre a janela **Central de importação**. A interface é feita com
Tkinter e os coletores são executados em uma thread de trabalho para que a
janela continue mostrando o andamento.

## Uso da interface

### Importar hotéis

1. Confirme se os hotéis que deseja importar estão cadastrados e marcados como
   ativos.
2. Use **Importar todos os hotéis ativos** para processar todos os ativos em
   sequência.
3. Ou use **Escolher hotéis...**, marque os hotéis desejados e clique em
   **Importar selecionados**. Essa lista contém somente hotéis ativos.
4. Se um hotel estiver selecionado no editor, o aplicativo salva e valida a
   configuração dele antes de iniciar. Se houver erro, corrija os dados e
   salve antes de importar.
5. Durante a coleta, os controles ficam desabilitados para evitar alterações
   na configuração enquanto o trabalho está em andamento.

O processamento é sequencial: termina a tentativa de um hotel antes de iniciar
o próximo. Uma falha individual é exibida no resultado daquele hotel e não
impede a tentativa dos demais hotéis selecionados.

### Resultado

Na tabela, cada hotel apresenta o estado da importação, dos relatórios e do
logout:

- **Concluído:** todos os relatórios esperados foram obtidos; no Desbravador,
  o logout também precisa ser confirmado.
- **Parcial:** ao menos um relatório foi obtido, mas outro relatório falhou ou
  alguma etapa necessária não foi confirmada.
- **Falhou:** nenhum relatório válido foi obtido ou não foi possível iniciar
  a coleta.

A área **Detalhes, arquivos gerados e erros** informa o progresso, o caminho
dos arquivos e a mensagem de falha. Senhas e nomes de usuário são removidos das
mensagens de erro produzidas pelo processamento em lote.

### Cadastrar, editar e remover hotéis

- **+ Novo hotel:** abre um perfil vazio.
- **Salvar configuração do hotel:** valida e grava as informações do perfil.
- **Remover:** solicita confirmação e remove o perfil e a credencial associada
  ao hotel no Gerenciador de Credenciais do Windows.
- **Incluir este hotel quando importar todos os ativos:** controla se o perfil
  participa da opção de importar todos. Hotéis inativos também não aparecem na
  seleção de importação.

Deixe o campo de senha vazio para manter a senha existente. Para alterar a
senha, digite a nova senha e salve.

## Cadastro e configuração

### Campos do perfil

- **Nome do hotel:** nome usado na interface e, conforme o coletor, nos nomes
  dos arquivos.
- **Sistema:** Desbravador Web, Queops ou AmerisConnect. AmerisConnect está
  visível apenas para identificar o perfil; não possui coletor disponível.
- **URL de acesso:** obrigatória para sistemas web e deve começar com `https://`.
- **Usuário:** login do sistema. É guardado no arquivo de configuração.
- **Senha:** salva no Gerenciador de Credenciais do Windows, não no JSON.
- **Nome atual no seletor:** nome que o Desbravador exibe para a unidade
  atualmente autenticada. É usado para validar a troca de unidade.
- **Unidade adicional após esta coleta:** opcional. O coletor executa C e R
  para o perfil principal, troca para essa unidade usando a mesma sessão e
  executa C e R novamente.
- **Filtros:** as abas C e R permitem manter o padrão do sistema, marcar ou
  desmarcar opções específicas do Desbravador.

Para Reservas (C), os filtros configuráveis são **Canceladas** e
**Listar reservas bloqueio**. Para Movimentação com diária (R), são:

- Considerar UHs em Manutenção no cálculo da ocupação;
- Considerar UHs em Uso da casa no cálculo da ocupação;
- Considerar refeições após o Check-out do dia.

Esses filtros e a troca de unidade são recursos do Desbravador. Para Queops,
as opções de filtro do Desbravador ficam desativadas.

### Formato do arquivo `hotels.json`

O arquivo contém os perfis e opções, não as senhas. Exemplo fictício:

```json
{
  "hotels": [
    {
      "id": "id-unico-do-hotel",
      "name": "Hotel Exemplo",
      "url": "https://desbravadorweb.com.br/acesso/1234",
      "username": "usuario@example.com",
      "system": "desbravador_web",
      "active": true,
      "additional_unit": "",
      "unit_selector_name": "HOTEL EXEMPLO",
      "disabled_reservation_filters": [],
      "reservation_filter_overrides": {},
      "movement_options": {}
    }
  ],
  "output_directory": "C:\\Users\\usuario\\Desktop",
  "output_format": "xls"
}
```

Valores possíveis para `system`:

- `desbravador_web`
- `queops_desktop`
- `amerisconnect` (perfil reconhecido, coletor indisponível)

Os campos `reservation_filter_overrides` e `movement_options` guardam opções
booleanas; quando não há uma opção explícita, o coletor mantém o padrão do
sistema. `disabled_reservation_filters` é mantido para compatibilidade com
perfis antigos.

O sistema procura primeiro por `hotels.json` junto aos arquivos do projeto.
Se esse arquivo não existir, usa
`%APPDATA%\PMSReportAutomation\hotels.json`. Portanto, ao executar o projeto
com uma configuração local presente, ela tem precedência sobre a configuração
em `%APPDATA%`.

O perfil Portinari/Centro recebe a unidade vinculada como valor padrão quando
seu nome ou a URL de acesso correspondem ao cadastro conhecido. O usuário pode
editar esses valores no perfil.

## Fluxo de importação

1. A interface seleciona os hotéis ativos solicitados.
2. Para cada perfil, lê a senha pelo identificador
   `PMSReportAutomation/{id}` no Gerenciador de Credenciais do Windows.
3. `batch.py` escolhe o coletor de acordo com o sistema configurado.
4. O coletor executa suas etapas e devolve um resultado por relatório.
5. `app.py` atualiza a tabela, registra progresso e mostra arquivos ou erros.
6. O próximo hotel é processado, mesmo que o anterior tenha falhado.

Uma importação interrompida ou parcial não apaga relatórios válidos já criados.
O sistema também não substitui arquivos existentes: consulte a regra de saída
de cada coletor antes de repetir uma execução.

## Coletor Desbravador Web

Módulo: `collectors/desbravador_web.py`.

### Sequência

1. Abre o Google Chrome em modo visível com um perfil persistente isolado pelo
   identificador do hotel.
2. Acessa a URL cadastrada, preenche usuário e senha e aguarda a confirmação do
   login.
3. Se a tela exibir avisos opcionais conhecidos, tenta dispensá-los.
4. Coleta os relatórios para a unidade principal:
   - **C — Reservas**;
   - **R — Movimentação com diária**.
5. Se houver unidade adicional, valida a unidade exibida no seletor antes de
   trocar e coleta C e R para ela.
6. Tenta fazer logout pelo menu do sistema e confirma que a tela de login
   voltou a aparecer.

Se o Desbravador informar que a conta já está conectada em outra sessão, a
automação para sem tentar desconectar a sessão existente.

### Período e arquivos

O período padrão começa no primeiro dia do mês atual e termina no último dia
do período anual calculado a partir desse mês. Por exemplo, para uma execução
em novembro de 2026, o período é de 01/11/2026 a 31/10/2027.

Os relatórios são exportados como CSV dentro do fluxo autenticado, convertidos
para Excel 97-2003 e validados. O processo ajusta os anos das datas do relatório
para o período configurado e verifica novamente as datas depois de salvar.
Arquivos `.xls` usam assinatura binária de Excel 97-2003 e respeitam os limites
desse formato.

Os arquivos vão para a Área de Trabalho do Windows:

- `C-{nome da unidade} DD-MM-AAAA.xls`
- `R-{nome da unidade} DD-MM-AAAA.xls`

A unidade Ponte da Amizade é abreviada como `AMIZADE` no nome do arquivo. O
coletor não substitui um arquivo existente: se o destino já existir, aquele
relatório é marcado como falha e a execução segue para as outras etapas.

Para uma unidade adicional, o conjunto esperado é de quatro arquivos: C e R
para a unidade principal e C e R para a unidade adicional.

## Coletor Queops

Módulo: `collectors/queops_desktop.py`.

O Queops é controlado por automação de janelas do Windows (`pywinauto`). A
automação pode reutilizar o Queops já aberto; caso contrário, tenta abrir o
atalho `PontalMundai.lnk` na Área de Trabalho. Por usar janelas e coordenadas
da interface desktop, não interaja com as janelas do Queops enquanto a coleta
estiver em execução.

### Relatórios e filtros

1. **Check-in's esperados (C-FUT):** mantém a data inicial apresentada pelo
   Queops, configura a data final para o mesmo dia e mês no ano seguinte,
   garante **Fechado** e **Diária** marcados e seleciona **Total de diárias**.
2. **Resumo de Ocupação (C-PAST):** em **Rel. Gerenciais > Relatório de
   Ocupação**, usa o primeiro dia do mês até ontem e seleciona **Empresa**.
3. **Previsão de Ocupação (R):** configura a data final para o mesmo dia e mês
   no ano seguinte, seleciona **Empresa**, mantém **Mostrar diárias fechadas**
   marcado e **Somente Reservas** desmarcado.
4. **Diário de situação (RDS):** em **Rel. Gerenciais**, usa o primeiro dia do
   mês até ontem e define ontem como data de referência, com os filtros padrão.

A automação tenta os quatro relatórios mesmo quando uma etapa falha. Ela não
faz logout do Queops (`logout_required` é falso), pois a coleta opera no
aplicativo desktop.

No primeiro dia do mês ainda não existe um dia anterior dentro do mesmo mês.
Nesse caso, C-PAST e RDS não têm período válido; o coletor informa o problema
antes de iniciar as etapas.

### Arquivos

Os arquivos são enviados à pasta `Downloads` do usuário, independentemente do
argumento de saída recebido pelo coletor:

- `C-FUT {primeira palavra do hotel} DD-MM.xls`
- `C-PAST {primeira palavra do hotel} DD-MM.xls`
- `R-{nome completo do hotel} DD-MM.xls`
- `rds-{primeira palavra do hotel} DD-MM.pdf`

Se um arquivo com o mesmo nome já existir, o coletor acrescenta um número ao
nome, como `... 2.xls`, `... 3.xls`, sem sobrescrever o original. Isso difere
do coletor Desbravador, que falha para aquele destino já existente.

Se aparecer o aviso de falha de conexão com CCQ, a automação fecha o aviso e
continua até o próximo passo possível. Isso não restabelece a conexão com o
servidor; o próprio Queops pode informar que será fechado após determinado
tempo.

## Arquivos, períodos e logs

| Conteúdo | Local padrão |
|---|---|
| Configuração dos hotéis | `hotels.json` no projeto; na ausência dele, `%APPDATA%\PMSReportAutomation\hotels.json` |
| Senhas | Gerenciador de Credenciais do Windows |
| Relatórios Desbravador | Área de Trabalho do Windows |
| Relatórios Queops | `Downloads` do usuário |
| Perfis de navegador Desbravador | `%LOCALAPPDATA%\PMSReportAutomation\browser-profiles` |
| Logs | `%LOCALAPPDATA%\PMSReportAutomation\logs\automation.log` |
| Logs, se a pasta principal estiver inacessível | `%TEMP%\PMSReportAutomation\logs\automation.log` |

Se o aplicativo não puder criar o perfil do Chrome no local padrão, ele tenta
usar `%TEMP%\PMSReportAutomation\browser-profiles` e informa a troca durante a
importação. Os dados de sessão do navegador ficam persistidos nesse local.
Os temporários internos do Playwright usam a subpasta `playwright-temp` ao
lado dos perfis para não depender de um `%TEMP%` sem permissão.

O aplicativo informa na tela quando precisou usar o caminho alternativo de
logs. Se não for possível gravar em nenhum dos locais, o aplicativo continua
sem log persistente e informa essa condição na tela.

O Desbravador usa `default_desktop_path()` para localizar a Área de Trabalho
configurada no Windows. O Queops usa a pasta `Downloads` do perfil do usuário.

## Estrutura do projeto

| Arquivo/pasta | Responsabilidade |
|---|---|
| `app.py` | Interface Tkinter, cadastro, seleção dos hotéis, andamento e resumo da importação. |
| `batch.py` | Filtra perfis ativos, obtém credenciais, escolhe o coletor e calcula o estado final por hotel. |
| `settings.py` | Modelos dos perfis, validação, leitura e gravação do JSON, caminhos padrão e valores conhecidos para Portinari/Centro. |
| `credentials.py` | Leitura, gravação e remoção de senhas pelo Gerenciador de Credenciais do Windows. |
| `periods.py` | Cálculo do período anual e do período do primeiro dia do mês até ontem. |
| `report_files.py` | Detecção de codificação CSV, conversão via Excel COM, correção de datas e validação dos `.xls`. |
| `collectors/desbravador_web.py` | Login web, avisos, relatórios C/R, troca de unidade e logout no Desbravador. |
| `collectors/queops_desktop.py` | Login, navegação, filtros e exportação dos quatro relatórios do Queops. |
| `collectors/models.py` | Estruturas comuns de resultado de coleta e de relatório. |
| `importar_pontal.py` | Entrada de linha de comando para importar o perfil ativo do Pontal usando Queops. |
| `tests/` | Testes unitários de configurações, credenciais, períodos, coletores, lotes e arquivos. |
| `PROMPT_IRACEMA.md` | Material de prompt auxiliar; não é usado pelo aplicativo e pode não refletir o estado atual do cadastro. |

Arquivos de diagnóstico ou temporários com nomes iniciados por `_` não fazem
parte do fluxo normal de importação. Revise-os antes de executar ou compartilhar:
alguns podem conter dados locais ou credenciais de teste.

## Testes

Execute a suíte completa:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes cobrem:

- seleção e processamento sequencial de hotéis ativos;
- redação de dados de usuário e senha em erros;
- configurações, migração de campos antigos e valores de Portinari/Centro;
- login, troca de unidade, ordem dos relatórios e logout do Desbravador;
- janelas, filtros, exportação e continuidade dos relatórios do Queops;
- cálculo de períodos;
- comportamento de conversão, datas e validação de arquivos;
- identificação dos sistemas exibidos e fallback de logs.

Testes que dependem de Excel COM podem ser ignorados quando Microsoft Excel ou
o suporte COM não estiver disponível no ambiente de teste.

## Solução de problemas

### Erro de acesso ao arquivo `automation.log`

Se `%LOCALAPPDATA%\PMSReportAutomation\logs` não puder ser acessado, o
aplicativo tenta `%TEMP%\PMSReportAutomation\logs` e mostra o caminho
alternativo na área de detalhes. A importação não depende de conseguir gravar
no primeiro caminho de log.

### Erro ao carregar `hotels.json`

Verifique se o JSON é válido, se o arquivo pode ser lido e se os campos
obrigatórios estão preenchidos. Quando existe um `hotels.json` ao lado do
projeto, ele tem precedência sobre `%APPDATA%`; confirme que está editando o
arquivo efetivamente utilizado.

### Senha não encontrada

Abra o perfil do hotel, informe a senha e salve. A senha é procurada no
Gerenciador de Credenciais do Windows usando o identificador do perfil.

### Login do Desbravador não confirmado

Confira URL, usuário e senha. Verifique também se a página de acesso mudou ou
se a conta já está conectada em outra sessão. O coletor não tenta desconectar
uma sessão em uso.

### Chrome ou tela do Queops não abre

Confirme que o Google Chrome está instalado para o Desbravador. Para Queops,
confirme que o aplicativo está instalado, que o atalho `PontalMundai.lnk` está
na Área de Trabalho ou que o Queops já está aberto em uma sessão interativa.
Não minimize nem use as janelas enquanto a coleta do Queops estiver rodando.

Se o log mostrar `EPERM` ao criar `playwright-artifacts`, feche e reabra o
aplicativo atualizado. Os temporários do Playwright são direcionados para uma
pasta gravável junto ao perfil do navegador.

### Falha ao criar `.xls`

Para o Desbravador, confirme que o Microsoft Excel está instalado e que
`pywin32` foi instalado no mesmo ambiente Python usado para iniciar o app.
Confira também se o arquivo de destino já existe e se a Área de Trabalho
permite gravação. O Excel agora salva e valida o `.xls` em uma área temporária;
depois o aplicativo publica o arquivo final na pasta de saída sem sobrescrever
um `.xls` existente.
Se a conversão falhar, a mensagem detalhada agora inclui a causa retornada pelo
Excel. Se uma janela do PMS bloquear os campos de data, a mensagem inclui o
texto dessa janela; verifique-a no Chrome antes de repetir a importação.

### Falha em um relatório, mas os outros foram gerados

Consulte a mensagem específica daquele relatório em **Detalhes, arquivos
gerados e erros**. Os coletores tentam continuar as etapas independentes. No
Queops, os arquivos já exportados permanecem em Downloads mesmo que outra
etapa falhe.

### Perfil AmerisConnect

O perfil é reconhecido e aparece na interface, mas o coletor ainda não está
disponível. Esse perfil será marcado como falha; os demais hotéis ativos
continuam sendo processados.

## Segurança e arquivos locais

- Senhas são armazenadas no Gerenciador de Credenciais do Windows; não são
  gravadas em `hotels.json`.
- `hotels.json` contém nomes de hotéis, usuários, URLs e demais configurações.
  Trate-o como dado operacional privado.
- Os logs não devem registrar senhas nem nomes de usuário; ainda assim, revise
  os arquivos locais antes de compartilhá-los.
- Perfis persistentes do Chrome podem conter dados de navegação da sessão do
  hotel. Eles ficam separados pelo identificador do perfil em
  `%LOCALAPPDATA%\PMSReportAutomation\browser-profiles`.
- Não compartilhe `.env`, `hotels.json`, logs, pastas de perfil do navegador ou
  scripts temporários sem revisar seu conteúdo.
- Antes de distribuir ou publicar o projeto, confira os scripts auxiliares
  `_setup_*` e `_inspect_*`; eles são locais e não são necessários para iniciar
  a interface.
