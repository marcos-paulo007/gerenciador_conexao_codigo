# updater.py
import sys
import os
import time
import subprocess
import shutil

# Este script espera 3 argumentos da linha de comando:
# 1. (sys.argv[0]): o nome do próprio script (updater.py)
# 2. (sys.argv[1]): O caminho do executável principal que será fechado (app_path)
# 3. (sys.argv[2]): O caminho do novo arquivo baixado (update_path)

try:
    app_path = sys.argv[1]
    update_path = sys.argv[2]

    # 1. Espera 3 segundos para o app principal fechar
    time.sleep(3)

    # 2. Substitui o arquivo antigo pelo novo
    #    (shutil.move funciona como "recortar" e "colar")
    shutil.move(update_path, app_path)

    # 3. Reinicia o aplicativo principal (agora já atualizado)
    subprocess.Popen([app_path])

    # 4. Termina a si mesmo
    sys.exit(0)

except Exception as e:
    # Se algo der errado, cria um log
    with open("updater_log.txt", "w") as f:
        f.write(f"Erro ao atualizar: {e}\n")
        f.write(f"App Path: {app_path}\n")
        f.write(f"Update Path: {update_path}\n")
    sys.exit(1)