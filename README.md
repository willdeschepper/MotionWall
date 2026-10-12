# MotionWall

Aplicativo de wallpapers animados para Ubuntu/GNOME, feito com Python,
GTK4/Libadwaita e WebKitGTK. Versão **0.2.3**, com integração GNOME experimental.

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
um GIF, uma animação Lottie, a Aurora em MP4 e uma chuva com alpha incluídos.

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

Para atualizar uma extensão já instalada, desative-a antes de copiar a nova
versão; o GNOME precisa de uma nova sessão para recarregar o módulo JavaScript:

```sh
gnome-extensions disable motionwall@willdeschepper.github.io
git pull --ff-only
./dev.sh --install-extension
```

Saia e entre novamente na sessão, ative a extensão e abra o aplicativo com os
comandos acima. A versão 0.2.1 corrige o filtro das miniaturas de workspace e
restringe a recuperação de foco ao espaço de trabalho atual. A animação fica
no desktop; as miniaturas do Overview usam o fundo estático do GNOME.

## Enquadramento e tamanho original

Em **Enquadramento**, escolha um dos quatro modos:

| Opção | Comportamento |
| --- | --- |
| Ajustar | Amplia ou reduz para caber na área, preservando a proporção. |
| Preencher | Amplia ou reduz para ocupar toda a área; as bordas podem ficar recortadas. |
| Esticar | Ocupa toda a área alterando a proporção. |
| Tamanho original · 100% | Centraliza sem redimensionar: um pixel do arquivo por pixel físico da tela. |

No modo 100%, um arquivo 800×450 ocupa 800×450 pixels, inclusive em telas HiDPI.
Se o arquivo for menor que a tela, há espaço ao redor; se for maior, as bordas
ficam recortadas. Para SVG, o tamanho vem das dimensões declaradas do arquivo,
ou do viewBox quando não há dimensões absolutas. Para Lottie, usa o tamanho da
composição. GIF e vídeo usam a resolução do arquivo.

A opção funciona na prévia e no wallpaper. Após mudar o enquadramento, clique
em **Aplicar como fundo** para atualizar a animação aplicada. A escolha é salva
entre execuções.

A extensão declara GNOME 46–50 e trata a mudança de API do Mutter 50.
A validação automática passou em sessões isoladas de GNOME 46/Wayland no
Ubuntu 24.04 e GNOME 50.1/Wayland no Ubuntu 26.04, com renderização por software.
É uma versão experimental; a validação em hardware e com outras extensões
depende do ambiente. O fundo é aplicado a todos os monitores e não altera os caminhos
do wallpaper estático. Ao bloquear a sessão ou desabilitar a extensão, o player
é encerrado; reaplique após desbloquear. Não há inicialização automática no login.

## Consumo de CPU e fluidez

SVG e Lottie usam um limite de **30 fps** por padrão, independente de telas de
120/144 Hz. Em **Fluidez**, escolha 15, 30 ou 60 fps. A duração e a velocidade
continuam iguais; o limite reduz a frequência de pintura. O controle vale para
SVG (CSS e SMIL) e Lottie; GIF e vídeo seguem os quadros do arquivo.

A Aurora SVG usa um desfoque animado. Em tela inteira, esse filtro continua
custoso mesmo com menos quadros. Para essa animação, use **aurora-video** em
**Importar exemplos**: a mesma cena foi pré-renderizada em H.264, 1920×540,
30 fps, sem áudio, com um loop de 18 segundos. Ela é ampliada normalmente no
monitor 3840×1080. O script `tools/build_aurora_video.py` reproduz a geração.
MP4 comum não contém alpha; esta alternativa é um fundo completo.

Trocar SVG por Lottie não garante economia: o Lottie Web deste aplicativo também
usa o renderer SVG. Vídeo evita recalcular curvas e desfoques, mas o custo da
decodificação depende do codec, da resolução e da aceleração disponível.

Feche a janela do catálogo depois de aplicar para não manter também a prévia
animando. A comparação automática usa a mesma Aurora, o mesmo WebKitGTK e uma
área 3840×1080, com renderização por software. O relatório inclui CPU de toda a
árvore de processos e quadros observados. Os resultados de CI não são uma
previsão do consumo no computador do usuário.

## Animação transparente sobre o wallpaper

Ative **Fundo transparente**, selecione uma animação que tenha alpha e clique
em **Aplicar como fundo**. A camada animada revela o wallpaper estático nas
áreas transparentes. O WebKit e a janela do renderer preservam alpha até a
composição do GNOME. Desative a opção para usar o fundo sólido do player.

O exemplo **chuva-alpha** é uma sobreposição de chuva sem fundo. Lottie, SVG
e GIF podem preservar transparência quando o arquivo a possui. A opção não
remove retângulos, imagens ou cores desenhados dentro da própria animação.
A Aurora SVG e a Aurora MP4 incluem o céu e as montanhas, portanto são opacas.
Transparência em codecs de vídeo depende do decoder; H.264/MP4 comum não a fornece.

Esta atualização também muda a ponte GNOME para repassar fluidez e transparência.
Desative a extensão, feche o catálogo, execute `git pull --ff-only` e
`./dev.sh --install-extension`. Saia e entre na sessão, ative a extensão e
reaplique. O módulo JavaScript do GNOME precisa ser recarregado.

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
local possuem testes automatizados. Aplicação, avanço da animação e restauração
passaram no teste isolado de GNOME Wayland para GIF, SVG e Lottie. Codecs de vídeo
em hardware e múltiplos monitores físicos ainda não foram validados.

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
O teste cobre VP8/WebM e H.264/MP4 com os plugins do CI. O teste de integração com wallpaper é separado:

```sh
sudo apt install xvfb dbus-x11 gnome-shell
xvfb-run -a dbus-run-session -- /usr/bin/python3 tests/desktop_smoke.py
```

Ele instala a extensão em uma pasta temporária, abre outra sessão GNOME com
suas próprias configurações e barramento, aplica GIF/SVG/Lottie/MP4, verifica avanço
da animação e restauração e desabilita a extensão. Também cria uma janela comum,
troca espaços por teclado, abre o Overview, verifica as miniaturas e move a janela
para outro espaço. Também compara os pixels do desktop antes, durante e depois da chuva, com alpha ativado e desativado. Não altera sua sessão principal.
O CI salva screenshot e logs nos artefatos `motionwall-desktop-test-ubuntu-24.04`
e `motionwall-desktop-test-ubuntu-26.04`.

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

Próximas etapas: validação em hardware, pausa por tela cheia e energia, controles
independentes por monitor, inicialização no login e empacotamento.

## Licenças

MotionWall: MIT. Lottie Web e omggif: MIT, com avisos preservados em
`motionwall/web/vendor`. Os exemplos incluídos pertencem ao projeto.

Para repetir a comparação de CPU em uma sessão de teste (não aplica fundo no desktop):

```sh
git show a842a549aea7ec900c64b90ee48162b1d77ca89f:motionwall/web/player.js > /tmp/motionwall-original-player.js
xvfb-run -a -s '-screen 0 3840x1080x24' dbus-run-session -- /usr/bin/python3 tests/playback_benchmark.py --baseline-player /tmp/motionwall-original-player.js
```

O CI executa esse teste sem aceleração de GPU para tornar a comparação explícita;
em uma máquina física, o resultado pode ser diferente. `smoke-output/playback-benchmark.json`
registra as medições. 100% de CPU corresponde a um processador lógico ocupado.
