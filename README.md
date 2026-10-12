# MotionWall

Aplicativo de wallpapers animados para Ubuntu com GNOME e Wayland.

## Estado do projeto

Projeto em desenvolvimento inicial. Este repositório ainda não contém um aplicativo executável ou integração com o desktop. Os formatos abaixo são metas de implementação, não recursos já disponíveis.

## Objetivo

Importar e reproduzir GIF, SVG animado, Lottie JSON, arquivos `.lottie`, MP4 e WebM, com uma galeria e pré-visualização antes de aplicar ao desktop.

Ambiente alvo de validação: Ubuntu 26.04, GNOME 50 e Wayland, incluindo monitor ultrawide 3840×1080.

## Arquitetura proposta

- Python + GTK4/Libadwaita: interface, galeria e configurações.
- WebKitGTK: reprodução de GIF, SVG e animações web em um processo separado do GNOME Shell.
- Lottie: biblioteca de reprodução empacotada localmente; avaliar separadamente Lottie JSON e o contêiner `.lottie`.
- Vídeos: avaliar WebKitGTK/GStreamer e disponibilidade dos codecs no ambiente alvo.
- Integração com o desktop: investigar uma extensão GJS mínima para GNOME Wayland, após validar o aplicativo e o renderer.

Um WebView comum não se torna automaticamente o fundo da área de trabalho no GNOME Wayland. A integração entre o renderer externo e o Shell precisa de uma prova de conceito antes de definir essa parte da arquitetura.

## Etapas

1. Criar aplicativo com galeria local, importação e pré-visualização de GIF e SVG animado.
2. Adicionar Lottie JSON, `.lottie` e vídeos, verificando suporte real de cada formato.
3. Implementar controles de reprodução e enquadramento, persistência e exemplos locais.
4. Validar a integração com o desktop em uma sessão GNOME isolada.
5. Adicionar múltiplos monitores, pausa automática e instalação empacotada.

## Critérios de implementação

- Não executar o motor de animação dentro do processo do GNOME Shell.
- Não instalar ou habilitar a extensão automaticamente na sessão principal.
- Manter dependências de reprodução locais, sem depender de CDN.
- Tratar arquivos importados como conteúdo não confiável: limitar acesso à rede e ao sistema de arquivos, e definir uma política explícita para scripts em SVG/HTML.
- Validar arquivos `.lottie` antes de extrair seu conteúdo, com limites de tamanho e proteção contra caminhos fora do diretório de destino.
- Incluir um comando de desenvolvimento e instruções compatíveis com Fish.
- Distinguir pré-visualização no aplicativo de aplicação real como wallpaper.

## Licença

Ainda não definida.
