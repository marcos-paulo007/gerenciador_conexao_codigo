import customtkinter as ctk
from tkinter import messagebox
import configparser
import os
import socket
import threading
import queue
import requests
import semver
import subprocess
import sys
import msvcrt
import tempfile

# --- CONFIGURAÇÕES GLOBAIS ---
CURRENT_VERSION = "1.2.2"  # Mude isso a cada nova versão gerada
VERSION_URL = "https://github.com/marcos-paulo007/Gerenciador-Conexao/releases/download/1.1.0/version.json"  # Seu URL real aqui
SENHA_CONFIG = "SuporteSortee"

# --- CONFIGURAÇÃO DOS CAMINHOS ---
PASTA_APP = r'C:\farmasys'
CAMINHO_LOJAS = os.path.join(PASTA_APP, 'lojas.ini')
CAMINHO_CONEXAO = os.path.join(PASTA_APP, 'conexao.ini')

# --- CONFIGURAÇÃO VISUAL ---
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- VARIÁVEIS GLOBAIS ---
config = configparser.ConfigParser()
lojas_disponiveis = []
janela_config_ref = None
loja_id_selecionado = None
loja_id_ativa_no_ini = None
status_labels = {}
resultados_queue = queue.Queue()
update_info = {}

# --- 1. VERIFICAÇÃO DE INSTÂNCIA ÚNICA ---
# Impede que o programa abra duas vezes
global lockfile_handle
lockfile_path = os.path.join(tempfile.gettempdir(), 'gerenciador_conexao_farmasys.lock')

try:
    if os.path.exists(lockfile_path):
        os.remove(lockfile_path)
    lockfile_handle = open(lockfile_path, 'w')
    msvcrt.locking(lockfile_handle.fileno(), msvcrt.LK_NBLCK, 1)
except (IOError, OSError):
    messagebox.showwarning("Aplicação em Execução",
                           "O Gerenciador de Conexão já está aberto.\n\n"
                           "Procure por ele na sua barra de tarefas.")
    sys.exit(0)

# --- Cria a pasta C:\farmasys se não existir ---
if not os.path.exists(PASTA_APP):
    try:
        os.makedirs(PASTA_APP)
    except OSError as e:
        messagebox.showerror("Erro Crítico",
                             f"Não foi possível criar a pasta de configuração:\n{PASTA_APP}\n\nErro: {e}")
        sys.exit()


# ==============================================================================
# FUNÇÕES DE SEGURANÇA E SISTEMA
# ==============================================================================

def verificar_farmasys_executando():
    """Verifica se o processo farmasys.exe está rodando no Windows."""
    try:
        output = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq farmasys.exe"',
            shell=True,
            creationflags=0x08000000
        ).decode('utf-8', errors='ignore')
        if "farmasys.exe" in output.lower():
            return True
        return False
    except Exception as e:
        print(f"Erro ao verificar processo: {e}")
        return False


# ==============================================================================
# FUNÇÕES DE ATUALIZAÇÃO AUTOMÁTICA (FORÇADA)
# ==============================================================================

def verificar_atualizacao_inicio():
    """Inicia a thread de verificação assim que o app abre."""
    threading.Thread(target=thread_verificar_versao, daemon=True).start()


def thread_verificar_versao():
    """Baixa o JSON e compara versões silenciosamente."""
    global update_info
    try:
        response = requests.get(VERSION_URL)
        if response.status_code != 200: return

        data = response.json()
        latest_version = data.get("latest_version")

        if semver.compare(latest_version, CURRENT_VERSION) > 0:
            update_info = data
            # Chama a função de bloqueio na thread principal
            if janela:
                janela.after(0, bloquear_e_atualizar)

    except Exception as e:
        print(f"Erro ao verificar atualização: {e}")


def bloquear_e_atualizar():
    """Bloqueia a tela e inicia o processo de atualização."""
    janela_update = ctk.CTkToplevel(janela)
    janela_update.title("Atualização Obrigatória")
    janela_update.geometry("350x150")
    janela_update.resizable(False, False)

    # Centraliza
    x = janela.winfo_x() + (janela.winfo_width() // 2) - 175
    y = janela.winfo_y() + (janela.winfo_height() // 2) - 75
    janela_update.geometry(f"+{x}+{y}")

    # Remove botão fechar e mantém no topo
    janela_update.protocol("WM_DELETE_WINDOW", lambda: None)
    janela_update.grab_set()
    janela_update.attributes("-topmost", True)

    ctk.CTkLabel(janela_update, text="Nova versão encontrada!",
                 font=ctk.CTkFont(size=16, weight="bold"), text_color="#00AEEF").pack(pady=(20, 10))

    ctk.CTkLabel(janela_update, text="Baixando atualização...\nPor favor, aguarde.",
                 font=ctk.CTkFont(size=12)).pack(pady=10)

    progresso = ctk.CTkProgressBar(janela_update, width=200)
    progresso.pack(pady=10)
    progresso.start()

    threading.Thread(target=download_silencioso_e_reiniciar, daemon=True).start()


def download_silencioso_e_reiniciar():
    """Baixa arquivos e executa updater."""
    try:
        temp_dir = tempfile.gettempdir()
        new_app_path = os.path.join(temp_dir, "app_update.exe")
        updater_path = os.path.join(temp_dir, "updater.exe")

        r_app = requests.get(update_info.get("app_url"))
        with open(new_app_path, 'wb') as f:
            f.write(r_app.content)

        r_updater = requests.get(update_info.get("updater_url"))
        with open(updater_path, 'wb') as f:
            f.write(r_updater.content)

        subprocess.Popen([updater_path, sys.executable, new_app_path])
        janela.after(0, janela.destroy)

    except Exception as e:
        messagebox.showerror("Erro Crítico", f"Falha na atualização automática:\n{e}")
        janela.after(0, janela.destroy)


# ==============================================================================
# FUNÇÕES DE LÓGICA DO NEGÓCIO (Conexão e Status)
# ==============================================================================

def verificar_conexao_socket(ip, porta):
    try:
        porta_int = int(porta)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        resultado = sock.connect_ex((ip, porta_int))
        sock.close()
        return resultado == 0
    except:
        return False


def verificar_todas_as_lojas_thread():
    config.read(CAMINHO_LOJAS)
    lojas_para_verificar = config.sections()
    status_resultados = {}
    for loja_id in lojas_para_verificar:
        if loja_id != loja_id_ativa_no_ini:
            ip = config.get(loja_id, 'ip', fallback=None)
            porta = config.get(loja_id, 'port', fallback='3306')
            if ip:
                status_resultados[loja_id] = "online" if verificar_conexao_socket(ip, porta) else "offline"
    resultados_queue.put(status_resultados)


def iniciar_verificacao_status():
    for loja_id, componentes in status_labels.items():
        if not componentes['is_active']:
            componentes['label'].configure(text="⚫", text_color="gray")
    threading.Thread(target=verificar_todas_as_lojas_thread, daemon=True).start()


def processar_resultados_queue():
    try:
        resultados = resultados_queue.get_nowait()
        for loja_id, status in resultados.items():
            if loja_id in status_labels and not status_labels[loja_id]['is_active']:
                if status == "online":
                    status_labels[loja_id]['label'].configure(text="🟢", text_color="green")
                else:
                    status_labels[loja_id]['label'].configure(text="🔴", text_color="red")
    except queue.Empty:
        pass
    finally:
        if janela: janela.after(100, processar_resultados_queue)


def conectar_loja():
    # --- SEGURANÇA: Verifica se Farmasys está aberto ---
    if verificar_farmasys_executando():
        messagebox.showwarning("Sistema em Execução",
                               "O Farmasys está aberto!\n\nPor favor, feche o aplicativo Farmasys antes de trocar a loja.")
        return

    if loja_id_selecionado is None:
        messagebox.showwarning("Atenção", "Por favor, selecione uma loja da lista.")
        return

    try:
        ip_novo = config.get(loja_id_selecionado, 'ip')
        porta_nova = config.get(loja_id_selecionado, 'port', fallback='3306')
        nome_da_loja = config.get(loja_id_selecionado, 'nome')
        caminho_novo = config.get(loja_id_selecionado, 'caminho_arquivos', fallback='ARQUIVOS')

        if not os.path.exists(CAMINHO_CONEXAO):
            messagebox.showerror("Erro", f"Arquivo conexao.ini não encontrado.")
            return

        with open(CAMINHO_CONEXAO, 'r', encoding='utf-8') as f:
            linhas = f.readlines()

        ip_antigo, porta_antiga = "", ""
        partes = linhas[0].split(';')
        for parte in partes:
            if 'server=' in parte: ip_antigo = parte.split('=')[1].strip()
            if 'port=' in parte: porta_antiga = parte.split('=')[1].strip()

        if ip_antigo and porta_antiga:
            linhas[0] = linhas[0].replace(f"server={ip_antigo}", f"server={ip_novo}") \
                .replace(f"port={porta_antiga}", f"port={porta_nova}")

        for i, linha in enumerate(linhas):
            if linha.strip().startswith("ARQUIVOS"):
                partes_linha = linha.split()
                novo_valor = f"\\\\{ip_novo}\\{caminho_novo}\\"
                linhas[i] = f"{partes_linha[0].ljust(19)}{novo_valor}\n"
                break

        with open(CAMINHO_CONEXAO, 'w', encoding='utf-8') as f:
            f.writelines(linhas)

        caminho_executavel = os.path.join(PASTA_APP, 'farmasys.exe')
        if os.path.exists(caminho_executavel):
            os.startfile(caminho_executavel)
            status_message_label.configure(text=f"Conectado à {nome_da_loja}!", text_color="green")
        else:
            status_message_label.configure(text=f"Conectado. 'farmasys.exe' não achado.", text_color="orange")

        janela.after(5000, lambda: status_message_label.configure(text=""))
        atualizar_lista_lojas()

    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao conectar:\n{e}")


# ==============================================================================
# FUNÇÕES DE GERENCIAMENTO (CRUD)
# ==============================================================================

def remover_loja():
    if loja_id_selecionado is None:
        messagebox.showwarning("Atenção", "Selecione a loja que deseja remover.")
        return
    if messagebox.askyesno("Confirmar", "Tem certeza que deseja remover esta loja?"):
        config.remove_section(loja_id_selecionado)
        with open(CAMINHO_LOJAS, 'w') as f: config.write(f)
        atualizar_lista_lojas()


def abrir_janela_edicao(loja_id_para_editar=None):
    janela_edicao = ctk.CTkToplevel(janela)
    janela_edicao.grab_set()
    janela_edicao.title("Editar Loja" if loja_id_para_editar else "Nova Loja")

    # Campos
    ctk.CTkLabel(janela_edicao, text="Nome:").grid(row=0, column=0, padx=10, pady=5)
    entry_nome = ctk.CTkEntry(janela_edicao, width=250);
    entry_nome.grid(row=0, column=1, padx=10)

    ctk.CTkLabel(janela_edicao, text="CNPJ:").grid(row=1, column=0, padx=10, pady=5)
    entry_cnpj = ctk.CTkEntry(janela_edicao, width=250);
    entry_cnpj.grid(row=1, column=1, padx=10)

    ctk.CTkLabel(janela_edicao, text="IP:").grid(row=2, column=0, padx=10, pady=5)
    entry_ip = ctk.CTkEntry(janela_edicao, width=250);
    entry_ip.grid(row=2, column=1, padx=10)

    ctk.CTkLabel(janela_edicao, text="Porta:").grid(row=3, column=0, padx=10, pady=5)
    entry_porta = ctk.CTkEntry(janela_edicao, width=250);
    entry_porta.grid(row=3, column=1, padx=10)

    ctk.CTkLabel(janela_edicao, text="Pasta:").grid(row=4, column=0, padx=10, pady=5)
    entry_caminho = ctk.CTkEntry(janela_edicao, width=250);
    entry_caminho.grid(row=4, column=1, padx=10)

    # Preenchimento se edição
    if loja_id_para_editar:
        entry_nome.insert(0, config.get(loja_id_para_editar, 'nome'))
        entry_cnpj.insert(0, config.get(loja_id_para_editar, 'cnpj'))
        entry_ip.insert(0, config.get(loja_id_para_editar, 'ip'))
        entry_porta.insert(0, config.get(loja_id_para_editar, 'port', fallback='3306'))
        entry_caminho.insert(0, config.get(loja_id_para_editar, 'caminho_arquivos', fallback='ARQUIVOS'))
    else:
        entry_porta.insert(0, "3306");
        entry_caminho.insert(0, "ARQUIVOS")

    def salvar():
        nome, cnpj, ip = entry_nome.get().strip(), entry_cnpj.get().strip(), entry_ip.get().strip()
        porta, caminho = entry_porta.get().strip() or "3306", entry_caminho.get().strip() or "ARQUIVOS"

        if not all([nome, cnpj, ip]):
            messagebox.showwarning("Erro", "Nome, CNPJ e IP são obrigatórios.", parent=janela_edicao)
            return

        id_salvar = loja_id_para_editar if loja_id_para_editar else f"LOJA_{nome.upper().replace(' ', '_')}"

        if not loja_id_para_editar and config.has_section(id_salvar):
            messagebox.showwarning("Erro", "Loja com nome similar já existe.", parent=janela_edicao);
            return

        if not config.has_section(id_salvar): config.add_section(id_salvar)

        config.set(id_salvar, 'nome', nome);
        config.set(id_salvar, 'cnpj', cnpj)
        config.set(id_salvar, 'ip', ip);
        config.set(id_salvar, 'port', porta)
        config.set(id_salvar, 'caminho_arquivos', caminho)

        with open(CAMINHO_LOJAS, 'w') as f:
            config.write(f)
        atualizar_lista_lojas();
        janela_edicao.destroy()

    ctk.CTkButton(janela_edicao, text="Salvar", command=salvar).grid(row=5, column=0, columnspan=2, pady=10)


def iniciar_edicao():
    if loja_id_selecionado:
        abrir_janela_edicao(loja_id_selecionado)
    else:
        messagebox.showwarning("Atenção", "Selecione uma loja.")


# ==============================================================================
# FUNÇÕES DE INTERFACE (GUI)
# ==============================================================================

def selecionar_loja(loja_id):
    global loja_id_selecionado
    loja_id_selecionado = loja_id
    for id_loja, comps in status_labels.items():
        comps['frame'].configure(fg_color="#E67E22" if id_loja == loja_id else "transparent")


def atualizar_lista_lojas():
    global lojas_disponiveis, loja_id_selecionado, status_labels, loja_id_ativa_no_ini

    # Descobre loja ativa
    loja_id_ativa_no_ini = None
    ip_ativo, porta_ativa = "", ""
    if os.path.exists(CAMINHO_CONEXAO):
        try:
            with open(CAMINHO_CONEXAO, 'r') as f:
                l = f.readline()
            for p in l.split(';'):
                if 'server=' in p: ip_ativo = p.split('=')[1].strip()
                if 'port=' in p: porta_ativa = p.split('=')[1].strip()
        except:
            pass

    # Limpa e Recria
    for w in frame_lista_lojas.winfo_children(): w.destroy()
    status_labels.clear();
    loja_id_selecionado = None

    config.read(CAMINHO_LOJAS)
    lojas_disponiveis = config.sections()

    for loja_id in lojas_disponiveis:
        frame = ctk.CTkFrame(frame_lista_lojas, fg_color="transparent")
        frame.grid_columnconfigure(0, minsize=30);
        frame.grid_columnconfigure(1, weight=1)

        lbl_status = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=14))
        lbl_status.grid(row=0, column=0, sticky="w", padx=5)

        ip = config.get(loja_id, 'ip', fallback="")
        porta = config.get(loja_id, 'port', fallback="3306")
        is_active = (ip == ip_ativo and porta == porta_ativa and ip_ativo != "")

        if is_active:
            loja_id_ativa_no_ini = loja_id
            lbl_status.configure(text="💻", text_color="#00AEEF")

        txt = f"{config.get(loja_id, 'nome')}\n(CNPJ: {config.get(loja_id, 'cnpj')})"
        btn = ctk.CTkButton(frame, text=txt, fg_color="transparent", anchor="w",
                            text_color=("gray10", "#DCE4EE"),
                            command=lambda i=loja_id: selecionar_loja(i))
        btn.grid(row=0, column=1, sticky="ew")
        frame.pack(fill="x", padx=5, pady=2)

        status_labels[loja_id] = {'frame': frame, 'label': lbl_status, 'is_active': is_active}

    iniciar_verificacao_status()


def ciclo_de_verificacao_status():
    iniciar_verificacao_status()
    if janela: janela.after(60000, ciclo_de_verificacao_status)


def pedir_senha_dialog():
    dialog = ctk.CTkToplevel(janela)
    dialog.title("Acesso Restrito")
    dialog.geometry("300x150")
    dialog.grab_set()

    senha = [None]

    def ok(): senha[0] = entry.get(); dialog.destroy()

    ctk.CTkLabel(dialog, text="Senha de Administrador:").pack(pady=10)
    entry = ctk.CTkEntry(dialog, show="*");
    entry.pack(pady=5);
    entry.focus()
    entry.bind("<Return>", lambda e: ok())
    ctk.CTkButton(dialog, text="OK", command=ok).pack(pady=10)

    janela.wait_window(dialog)
    return senha[0]


def abrir_tela_configuracao():
    global janela_config_ref
    if janela_config_ref and janela_config_ref.winfo_exists():
        janela_config_ref.lift();
        return

    senha = pedir_senha_dialog()
    if senha == SENHA_CONFIG:
        janela_config_ref = ctk.CTkToplevel(janela)
        janela_config_ref.title("Configurações")
        janela_config_ref.geometry("450x100")
        f = ctk.CTkFrame(janela_config_ref, fg_color="transparent")
        f.pack(pady=20)
        ctk.CTkButton(f, text="Adicionar", command=abrir_janela_edicao).pack(side="left", padx=5)
        ctk.CTkButton(f, text="Editar", command=iniciar_edicao).pack(side="left", padx=5)
        ctk.CTkButton(f, text="Remover", command=remover_loja, fg_color="#D32F2F").pack(side="left", padx=5)
    elif senha is not None:
        messagebox.showerror("Erro", "Senha incorreta.")


# ==============================================================================
# MAIN (EXECUÇÃO PRINCIPAL)
# ==============================================================================

janela = None  # Inicializa variável global

if __name__ == "__main__":
    janela = ctk.CTk()
    janela.title("Gerenciador de Conexão Farmasys")

    try:
        janela.iconbitmap("icon.ico")
    except:
        pass

    janela.geometry("450x420")
    janela.resizable(False, False)

    ctk.CTkLabel(janela, text="Selecione a loja para conectar:", font=ctk.CTkFont(size=14, weight="bold")).pack(
        pady=(10, 5))

    frame_lista_lojas = ctk.CTkScrollableFrame(janela, height=150)
    frame_lista_lojas.pack(fill="x", padx=10, expand=True)

    frame_btns = ctk.CTkFrame(janela, fg_color="transparent")
    frame_btns.pack(pady=20)

    ctk.CTkButton(frame_btns, text="Conectar", command=conectar_loja, height=35,
                  fg_color="#E67E22", hover_color="#D35400").pack(side="left", padx=5)
    ctk.CTkButton(frame_btns, text="Configurações", command=abrir_tela_configuracao,
                  fg_color="gray50", height=35).pack(side="left", padx=5)
    ctk.CTkButton(frame_btns, text="🔄", command=iniciar_verificacao_status, width=35, height=35).pack(side="left",
                                                                                                      padx=5)

    status_message_label = ctk.CTkLabel(janela, text="")
    status_message_label.pack(pady=(5, 10))

    # Inicialização
    atualizar_lista_lojas()
    processar_resultados_queue()
    ciclo_de_verificacao_status()
    verificar_atualizacao_inicio()

    janela.mainloop()