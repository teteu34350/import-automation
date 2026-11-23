# Prompt para explicar a importação do hotel Iracema

Você é um assistente técnico especializado na automação deste projeto.

Explique como funciona a **importação de relatórios do hotel Iracema** para uma
equipe técnica não especialista.

Baseie a resposta somente nas informações deste projeto e não invente dados.

## Contexto conhecido

- O projeto importa relatórios de hotéis usando a aplicação gráfica `app.py`.
- Atualmente há dois sistemas suportados:
  - **Desbravador Web**: coleta feita no navegador Google Chrome.
  - **Queops**: coleta feita por automação do aplicativo instalado no Windows.
- A seleção ativa é feita pelo perfil cadastrado do hotel. Apenas hotéis com
  `active = true` são enviados à importação.
- As credenciais ficam no Gerenciador de Credenciais do Windows. O usuário fica
  no perfil do hotel e a senha é recuperada pelo identificador
  `PMSReportAutomation/{id}`.
- As senhas e os nomes de usuário não devem aparecer em logs ou na resposta.
- Os arquivos gerados recebem nomes seguros e não substituem arquivos
  existentes. Reimportações no mesmo dia recebem sufixos como `(2)`, `(3)` etc.

## Fluxo geral

1. O usuário abre o aplicativo e seleciona um ou todos os hotéis ativos.
2. O sistema obtém o perfil do hotel e, em seguida, lê sua senha.
3. Conforme `hotel.system`, ele executa o coletor Desbravador Web ou Queops.
4. O coletor gera os relatórios do período configurado e tenta encerrá-los ou
   fazer logout quando necessário.
5. Ao terminar, a interface mostra:
   - **Concluído**: todos os relatórios esperados foram obtidos.
   - **Parcial**: pelo menos um relatório foi obtido, mas a coleta não ficou
     integralmente concluída.
   - **Falhou**: nenhum resultado válido foi obtido ou faltaram dados essenciais.
6. Os erros devem ser resumidos sem credenciais, detalhes sensíveis ou textos
   excessivamente técnicos.

## Importação por Desbravador Web

Se o perfil do Iracema estiver configurado como `desbravador_web`, explique:

- O Chrome é aberto com um perfil persistente isolado pelo identificador do
  hotel.
- A automação acessa a URL cadastrada, informa usuário e senha e aguarda o
  login.
- A tela inicial de avisos pode ser tratada automaticamente quando exibida.
- Se a unidade estiver configurada como uma unidade adicional, o sistema troca
  para ela somente após validar o hotel exibido no seletor.
- São coletados os relatórios C (Reservas) e R (Movimentação com diária).
- O período padrão é o mês atual completo até o último dia do mês seguinte,
  ou seja, do primeiro dia do mês atual até o último dia do ano seguinte.
- Os CSVs são convertidos e validados como Excel 97-2003 (`.xls`), com as datas
  ajustadas ao período.
- O resultado é salvo no diretório configurado.

## Importação por Queops

Se o perfil do Iracema estiver configurado como `queops_desktop`, explique:

- A automação tenta abrir o atalho `PontalMundai` da Área de Trabalho.
- Em seguida, faz login no aplicativo e aguarda a tela principal.
- São tratados avisos conhecidos de conexão com CCQ sem tentar uma reconexão
  manual nem encerrar a sessão.
- Os relatórios esperados são:
  1. Check-in's esperados — C-FUT.
  2. Resumo de Ocupação — C-PAST.
  3. Previsão de Ocupação — R.
  4. Diário de situação — RDS.
- A automação tenta continuar os quatro relatórios mesmo que um deles falhe.
- Os arquivos são exportados como Excel `.xls` ou PDF, conforme o relatório.
- Os arquivos são enviados para Downloads ou para o diretório configurado pela
  interface, sem substituir arquivos existentes.

## Atenção sobre o Iracema

Não há atualmente um perfil chamado **Iracema** no arquivo local de configurações
conhecido pelo projeto. Portanto:

- Não atribua ao Iracema o sistema do Lexy, do Poty, do Centro ou do Pontal do
  Mundai.
- Não invente URL, usuário, senha, unidade ou filtro.
- Antes de dar instruções operacionais definitivas, declare qual sistema deve
  ser usado: **Desbravador Web** ou **Queops**.
- Se o sistema não estiver informado, peça esse dado e peça também a URL de
  acesso ou a confirmação de que o atalho do Queops está disponível.

## Estrutura do projeto relevante

- `app.py`: interface e gerenciamento da importação.
- `batch.py`: seleção dos hotéis ativos e escolha do coletor.
- `settings.py`: perfil, sistema e configurações dos hotéis.
- `collectors/desbravador_web.py`: automação do Desbravador Web.
- `collectors/queops_desktop.py`: automação do Queops.
- `collectors/models.py`: status e resultado da coleta.
- `periods.py`: cálculo dos períodos dos relatórios.
- `report_files.py`: conversão e validação dos arquivos.
- `README.md`: visão geral e procedimentos conhecidos.

## Formato da resposta

Responda em português brasileiro, em linguagem clara e objetiva.

Inclua:

1. Qual é o sistema usado pelo Iracema, apenas se essa informação estiver
   disponível.
2. Pré-requisitos do hotel e do computador.
3. Passo a passo da importação.
4. Relatórios esperados.
5. Onde os arquivos são gravados.
6. Como interpretar Concluído, Parcial e Falhou.
7. Principais erros que podem ocorrer e a solução segura.

Não use a senha real nem dados pessoais de usuário. Não diga que uma conexão
CCQ foi restaurada: confirme apenas que o aviso foi fechado e que o sistema
continuou até o próximo passo possível.
