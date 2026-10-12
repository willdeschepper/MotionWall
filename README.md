# MotionWall

Biblioteca e prévia de animações para Ubuntu/GNOME, feita com Python,
GTK4/Libadwaita e WebKitGTK. Versão **0.2.0**, com integração GNOME experimental.

Importe uma animação, veja a prévia e clique em **Aplicar como fundo**. No
GNOME Wayland, isso requer a extensão MotionWall Desktop. A animação roda em
um processo independente e continua quando você fecha a janela do catálogo.
**Restaurar fundo** encerra o player e revela o wallpaper original.

## Instalar e abrir

No terminal (Bash ou Fish):

```sh
sudo apt update
sudo apt install git python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
git clone --branch feat/native-preview https://github.com/willdeschepper/MotionWall.git
cd MotionWall
./dev.sh --doctor
./dev.sh
```

O código está na branch `feat/native-preview`, em revisão no PR #1. Se já clonou
o repositório, execute `git fetch origin`, `git switch feat/native-preview` e
`git pull --ff-only` na pasta antes de abrir. Preserve alterações locais antes
de trocar de branch.
O aplicativo usa o Python do sistema; não precisa de pip ou ambiente virtual.

Use **Importar** ou arraste arquivos sobre a janela. Para começar sem baixar
animações, abra o menu e escolha **Importar exemplos**. Há um SVG ultrawide,
um GIF e uma animação Lottie incluídos.

## Ativar o fundo animado no GNOME Wayland

Na pasta do projeto:

```sh
./dev.sh --install-extension
```

Na primeira instalação, saia e entre novamente na sessão do GNOME para que
ele descubra a extensão. Salve seu trabalho antes de sair. Depois execute:

```sh
gnome-extensions enable motionwall@willdeschepper.github.io
./dev.sh
```

Selecione uma animação e clique em **Aplicar como fundo**, no topo da janela.
As opções de enquadramento, velocidade e loop são copiadas na aplicação;
para mudar as opções do fundo ativo, ajuste a prévia e aplique novamente.
Para voltar ao fundo normal, clique em **Restaurar fundo**. A janela do
catálogo também oferece a instalação da integração se ela estiver ausente.

A extensão declara GNOME 46–50 e trata a mudança de API do Mutter 50.
A validação automática usa uma sessão GNOME 46/Wayland isolada no Ubuntu 24.04;
Ubuntu 26.04/GNOME 50 ainda requer validação no ambiente alvo. É uma versão
experimental. O fundo é aplicado a todos os monitores e não altera os caminhos
do wallpaper estático. Ao bloquear a sessão ou desabilitar a extensão, o player
é encerrado; reaplique após desbloquear. Não há inicialização automática no login.

## Recursos desta versão

- Catálogo local com busca, cópia dos arquivos importados e remoção sem alterar os originais.
- Prévia, pausa, reinício, velocidade e enquadramento.
- Proporções 16:9, 32:9 e 4:3; 32:9 corresponde ao monitor 3840×1080.
- Configurações e seleção salvas entre execuções.
- Reprodução suspensa ao ocultar a janela.
- Player e bibliotecas JavaScript locais, sem CDN.
- Aplicar/restaurar wallpaper no GNOME Wayland, com renderer separado e múltiplas superfícies.

| Formato | Implementação e limites |
| --- | --- |
| GIF | Decodificação em Canvas; pausa, velocidade e loop; até 64 MiB e 16 milhões de pixels por quadro. |
| SVG | Animações CSS e SMIL; scripts, eventos JS e HTML embutido são rejeitados. O loop é definido pelo arquivo SVG. |
| Lottie JSON | Lottie Web light; imagens/fontes locais são copiadas. Expressões After Effects são rejeitadas. |
| `.lottie` | Pacotes v1/v2: importa a animação inicial ou a primeira. Não implementa state machines, temas ou interatividade dotLottie. |
| MP4 / WebM | Player WebKit/GStreamer, sem áudio; depende dos codecs instalados. |

Importar um arquivo não garante que todos os efeitos dele sejam compatíveis com
o renderer. Erros de reprodução aparecem na janela. O catálogo e o servidor
local possuem testes automatizados; a validação final no Ubuntu 26.04 com
GNOME 50/Wayland ainda precisa ocorrer.

## Dados e desenvolvimento

O catálogo fica em `~/.local/share/motionwall` (ou em `$XDG_DATA_HOME/motionwall`).
Para experimentar sem alterar seu catálogo:

```sh
./dev.sh --data-dir /tmp/motionwall-dev
```

```sh
./dev.sh --import motionwall/examples/aurora.svg
./dev.sh --list
/usr/bin/python3 -m unittest discover -s tests -v
./dev.sh --smoke-test
```

`--smoke-test` cria um catálogo temporário, abre GTK/WebKit e verifica avanço e
pausa de GIF, SVG, Lottie e `.lottie`. Requer uma sessão gráfica; em CI usa Xvfb.
O teste não cobre codecs de vídeo. O teste de integração com wallpaper é separado:

```sh
sudo apt install xvfb dbus-x11 gnome-shell
xvfb-run -a dbus-run-session -- /usr/bin/python3 tests/desktop_smoke.py
```

Ele instala a extensão em uma pasta temporária, abre outra sessão GNOME com
suas próprias configurações e barramento, aplica GIF/SVG/Lottie, verifica avanço
da animação e restauração e desabilita a extensão. Não altera sua sessão principal.
O CI salva screenshot e logs no artefato `motionwall-desktop-test`.

## Arquitetura e próximas etapas

`motionwall/library.py` valida e mantém o catálogo. `server.py` serve apenas o
player e arquivos importados por um endereço loopback com token aleatório.
`app.py` contém a interface GTK4; `web/player.js` reproduz as animações no
processo WebKit. O servidor não oferece escrita e restringe caminhos e recursos
externos. SVG com JavaScript e HTML arbitrário não são aceitos nesta versão.

`extension/extension.js` exporta uma ponte D-Bus e lança `renderer.py` por um
cliente Wayland privado do Mutter. A extensão só reconhece janelas pertencentes
a esse cliente e clona suas superfícies nos atores de background. GIF/Lottie/SVG
e vídeo continuam sendo reproduzidos no processo WebKit. O compositor não executa
o motor de animação. A restauração remove os clones, os handlers e o processo.

Próximas etapas: validação no GNOME 50, pausa por tela cheia e energia, controles
independentes por monitor, inicialização no login e empacotamento.

## Licenças

MotionWall: MIT. Lottie Web e omggif: MIT, com avisos preservados em
`motionwall/web/vendor`. Os exemplos incluídos pertencem ao projeto.
