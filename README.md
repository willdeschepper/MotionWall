# MotionWall

Biblioteca e prévia de animações para Ubuntu/GNOME, feita com Python,
GTK4/Libadwaita e WebKitGTK. Versão inicial **0.1.0**.

**Esta versão reproduz animações em uma janela. Ainda não aplica animações ao
papel de parede no GNOME Wayland.** Não instala extensões no GNOME Shell.

## Instalar e abrir

No terminal (Bash ou Fish):

```sh
sudo apt update
sudo apt install git python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
git clone https://github.com/willdeschepper/MotionWall.git
cd MotionWall
./dev.sh --doctor
./dev.sh
```

Se já clonou o repositório, execute `git pull --ff-only` na pasta antes de abrir.
O aplicativo usa o Python do sistema; não precisa de pip ou ambiente virtual.

Use **Importar** ou arraste arquivos sobre a janela. Para começar sem baixar
animações, abra o menu e escolha **Importar exemplos**. Há um SVG ultrawide,
um GIF e uma animação Lottie incluídos.

## Recursos desta versão

- Catálogo local com busca, cópia dos arquivos importados e remoção sem alterar os originais.
- Prévia, pausa, reinício, velocidade e enquadramento.
- Proporções 16:9, 32:9 e 4:3; 32:9 corresponde ao monitor 3840×1080.
- Configurações e seleção salvas entre execuções.
- Reprodução suspensa ao ocultar a janela.
- Player e bibliotecas JavaScript locais, sem CDN.

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
O teste não cobre codecs de vídeo nem integração com wallpaper.

## Arquitetura e próximas etapas

`motionwall/library.py` valida e mantém o catálogo. `server.py` serve apenas o
player e arquivos importados por um endereço loopback com token aleatório.
`app.py` contém a interface GTK4; `web/player.js` reproduz as animações no
processo WebKit. O servidor não oferece escrita e restringe caminhos e recursos
externos. SVG com JavaScript e HTML arbitrário não são aceitos nesta versão.

A próxima etapa é uma prova de conceito de integração com o GNOME Wayland,
testada em uma sessão isolada. Em seguida: múltiplos monitores, pausa automática
por tela cheia e empacotamento. Um WebView comum não ocupa a camada de wallpaper
do GNOME; essa integração ainda não está implementada.

## Licenças

MotionWall: MIT. Lottie Web e omggif: MIT, com avisos preservados em
`motionwall/web/vendor`. Os exemplos incluídos pertencem ao projeto.
