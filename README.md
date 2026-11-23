# Mini Video Studio

![capa](https://i.imgur.com/ouVgkXr.png)

Central de ferramentas para **converter, comprimir, cortar e analisar vídeos e áudios**, com interface
desktop escura e moderna. Tudo é processado **localmente** com FFmpeg: nenhum arquivo sai do seu computador.

- Python 3.14 (funciona a partir do 3.10) + Tkinter — **sem nenhuma biblioteca pip**
- FFmpeg e FFprobe no `PATH` (ou informados nas Configurações)
- Windows 10/11 (o código também roda em Linux/macOS)

## Como executar

```bat
python main.py            :: abre o aplicativo
python main.py --check    :: só verifica o FFmpeg/FFprobe (diagnóstico)
```
ou baixe o executável
## Instalador Executável
[Baixar pelo Drive](https://drive.google.com/file/d/1NtSOsP1JdhNANq3DT-JbNutvRPg5umQ2/view?usp=sharing)

No instalador vem por padrão o ffmpeg, que também adiciona na variável de ambiente

### Instalando o FFmpeg no Windows

1. Baixe o FFmpeg em <https://www.gyan.dev/ffmpeg/builds/> (versão *release essentials*) ou pelo instalador do programa.
2. Extraia, por exemplo, em `C:\ffmpeg`.
3. Adicione `C:\ffmpeg\bin` à variável de ambiente `PATH` e reabra o programa.

Se preferir não mexer no `PATH`, abra **Configurações → FFmpeg e FFprobe → Escolher executável…**
ou use o botão **Informar a pasta…** que aparece ao iniciar sem o FFmpeg.

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| **Início** | Acesso rápido às ferramentas, tarefas concluídas, status do FFmpeg/FFprobe e últimos arquivos processados. |
| **Conversor de vídeo** | MP4, MKV, AVI, MOV e WebM; escolha de codecs (só os que seu FFmpeg tem), resolução, FPS e bitrate; vários arquivos em fila. |
| **Compressor** | Perfis *Alta qualidade*, *Equilibrado* e *Arquivo pequeno*; barra de qualidade ligada ao CRF; preset; limite de resolução (nunca amplia); mostra a economia em %. |
| **Extrator de áudio** | MP3, WAV, AAC (.m4a), FLAC e OPUS, com bitrate / profundidade / nível de compressão, taxa de amostragem e canais. |
| **Extrator de frames** | Pré-visualização real do instante, PNG ou JPG, passos de 1 s / 1 frame e extração em intervalos para uma pasta. |
| **Analisador de mídia** | Duração, resolução, FPS, bitrates, codecs, taxa de amostragem, canais, tamanho e contêiner (via FFprobe); copia o relatório. |
| **Cortador de vídeo** | Início e fim com miniaturas; *corte rápido* (sem recodificar) ou *corte preciso* (recodifica); escolha do formato de saída. |
| **Conversor de áudio** | Conversão entre MP3, WAV, FLAC, AAC e OPUS. |

Todas as operações rodam **em segundo plano** (a janela nunca congela), mostram o **progresso real** do FFmpeg
(`-progress pipe:1`), entram numa **fila** e podem ser **canceladas** (arquivos incompletos são apagados).
Nenhum arquivo original é alterado ou sobrescrito: nomes repetidos recebem “ (2)”, “ (3)”…

## Atalhos de teclado

Funcionam quando você **não** está digitando em um campo de texto (exceto F1, Esc e Ctrl+Q).
Todos podem ser alterados em **Configurações → Atalhos de teclado**.

| Atalho | Ação | Atalho | Ação |
|---|---|---|---|
| Ctrl + O | Abrir arquivo | Ctrl + 1 … 8 | Início, Conversor, Compressor, Extrator de áudio, Extrator de frames, Analisador, Cortador, Conversor de áudio |
| Ctrl + Shift + O | Abrir vários arquivos | Ctrl + , | Configurações |
| Ctrl + E | Conversor de vídeo | F1 | Ajuda |
| Ctrl + Shift + C | Compressor | F5 | Atualizar informações |
| Ctrl + Shift + A | Extrator de áudio | Esc | Cancelar operação / fechar diálogo |
| Ctrl + I | Analisador | Ctrl + S | Salvar as opções da ferramenta |
| Ctrl + Q | Sair | | |

## Configurações

Salvas em `config/settings.json` (criado na primeira execução): pasta padrão de exportação, tema (destaque
azul ou roxo), notificações (status, som ou aviso ao terminar tudo), tarefas simultâneas (1–8), caminhos do
FFmpeg/FFprobe, atalhos personalizados, últimas opções de cada ferramenta (Ctrl+S) e histórico recente.

## Arquitetura

```
MiniVideoStudio/
├── main.py                 # ponto de entrada
├── core/                   # lógica de mídia — NÃO importa Tkinter
│   ├── ffmpeg.py           # localizar/validar, executar com progresso, cancelar, traduzir erros
│   ├── ffprobe.py          # metadados (JSON) → MediaInfo
│   ├── task_manager.py     # fila, threads, estados, cancelamento
│   ├── converter.py  compressor.py  audio.py  frames.py  cutter.py   # montam os comandos
│   └── analyzer.py         # relatório do analisador
├── ui/                     # interface Tkinter
│   ├── main_window.py  sidebar.py  base_view.py  theme.py  widgets.py
│   ├── task_panel.py  file_list.py  single_video.py  time_controls.py
│   └── home.py  converter_view.py  compressor_view.py  audio_view.py  frames_view.py
│       analyzer_view.py  cutter_view.py  settings_view.py  shortcuts_view.py
├── utils/                  # config.py, file_utils.py, validators.py, shortcuts.py
├── tests/                  # 130+ testes com FFmpeg real
├── assets/icons/           # (reservado; os ícones são glifos Unicode)
└── config/settings.json    # gerado na primeira execução
```

**Como as camadas conversam**

1. A interface cria um `Job` (comando do FFmpeg + metadados) e entrega ao `TaskManager`. **Ela nunca chama `subprocess`.**
2. Threads de trabalho executam o job e publicam eventos numa `queue.Queue`; **nenhuma thread toca em widgets**.
3. A janela principal chama `tasks.pump()` a cada 100 ms (`root.after`) e os *listeners* (painéis, barra de
   status, tela inicial) atualizam a tela já na thread do Tkinter.
4. Cancelar pede ao FFmpeg que finalize (`q`), depois `terminate()` e, se preciso, `kill()`.

## Testes

```bash
python -m unittest discover -s tests -t . -v
# Linux sem tela: xvfb-run -a python -m unittest discover -s tests -t . -v
```

Os testes geram vídeos de exemplo com o próprio FFmpeg, convertem/cortam/extraem de verdade e conferem o
resultado com o FFprobe. Os testes de interface precisam de um display (no Windows rodam normalmente).

## Limitações conhecidas

- O Tkinter não reproduz vídeo: a pré-visualização é a **imagem** de um instante, gerada pelo FFmpeg.
- Arrastar e soltar arquivos exigiria uma biblioteca externa; use **Ctrl+O** ou os botões de escolher arquivo.
- O **corte rápido** só corta em quadros-chave: o início pode ficar alguns segundos antes do tempo escolhido.
- AAC é salvo como `.m4a`; Opus como `.opus` (contêiner Ogg).
- Mudar a cor de destaque exige reiniciar (o programa oferece reiniciar na hora).

## Solução de problemas

| Sintoma | O que fazer |
|---|---|
| “FFmpeg não encontrado” ao abrir | Siga *Instalando o FFmpeg* acima ou use **Informar a pasta…**. |
| Um codec não aparece na lista | Seu FFmpeg não o inclui. Veja os disponíveis em **Configurações → FFmpeg e FFprobe**. |
| Uma conversão deu erro | Clique em **Detalhes** na tarefa: a mensagem explica o motivo e mostra a saída técnica do FFmpeg. |
| Atalho não funciona | Verifique se o foco não está num campo de texto e se ele não foi alterado nas Configurações. |
| Configurações estranhas | Apague `config/settings.json`: ele é recriado com os padrões (um arquivo corrompido é guardado como `.bak`). |
