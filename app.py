import sys
import os
import shutil
import sqlite3
import pandas as pd
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import tempfile
import platform
import subprocess

# GUI
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
# Atualize a importação para incluir ImageResampling.
from PIL import Image, ImageTk
import ttkbootstrap as ttkb  # Substituir tkinter por ttkbootstrap para temas modernos
from ttkbootstrap.constants import *  # Importar constantes para estilos

# Impressão
import win32print
import win32ui
from PIL import Image, ImageWin

import multiprocessing


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class PDVSystem:
    def __init__(self):
        logo_image = Image.open(resource_path('logo_casa_das_massas.png'))
        if getattr(sys, 'frozen', False):
            # Executando como executável
            self.db_path = os.path.join(os.path.dirname(
                sys.executable), 'pdv_database.db')
        else:
            self.db_path = os.path.join(
                os.path.dirname(__file__), 'pdv_database.db')
        self.setup_database()
        self.setup_gui()  # Mover a inicialização de cpf_var para dentro de setup_gui
        self.setup_keyboard_shortcuts()

    def setup_keyboard_shortcuts(self):
        """Configura os atalhos de teclado do sistema"""
        # Atalhos globais
        self.root.bind('<F1>', lambda e: self.show_shortcuts_help())
        self.root.bind('<F2>', lambda e: self.adicionar_produto())
        self.root.bind('<F3>', lambda e: self.adicionar_produto_kg())
        self.root.bind('<F4>', lambda e: self.aplicar_desconto())
        self.root.bind('<F5>', lambda e: self.finalizar_venda())
        self.root.bind('<F9>', lambda e: self.cancelar_compra())
        self.root.bind('<F12>', lambda e: self.gerenciar_produtos())

        # Atalhos com Ctrl
        self.root.bind('<Control-n>', lambda e: self.cancelar_compra())
        self.root.bind('<Control-f>', lambda e: self.finalizar_venda())
        self.root.bind('<Control-d>', lambda e: self.aplicar_desconto())
        self.root.bind('<Control-p>', lambda e: self.gerenciar_produtos())
        self.root.bind('<Control-r>', lambda e: self.exibir_relatorio_vendas())
        self.root.bind('<Control-q>', lambda e: self.root.quit())

        # Navegação entre campos
        self.root.bind('<Alt-1>', lambda e: self.code_entry.focus())
        self.root.bind('<Alt-2>', lambda e: self.received_entry.focus())
        self.root.bind(
            '<Alt-3>', lambda e: self.focus_payment_method('dinheiro'))
        self.root.bind(
            '<Alt-4>', lambda e: self.focus_payment_method('debito'))
        self.root.bind(
            '<Alt-5>', lambda e: self.focus_payment_method('credito'))
        self.root.bind('<Alt-6>', lambda e: self.focus_payment_method('pix'))

        # Atalhos numéricos para formas de pagamento
        self.root.bind(
            '<Key-1>', lambda e: self.set_payment_method('dinheiro') if e.state == 0 else None)
        self.root.bind(
            '<Key-2>', lambda e: self.set_payment_method('debito') if e.state == 0 else None)
        self.root.bind(
            '<Key-3>', lambda e: self.set_payment_method('credito') if e.state == 0 else None)
        self.root.bind(
            '<Key-4>', lambda e: self.set_payment_method('pix') if e.state == 0 else None)

        # Calcula troco com Enter quando no campo recebido
        self.received_entry.bind('<Return>', lambda e: self.calcular_troco())

        # Delete para remover item selecionado
        self.tree.bind('<Delete>', lambda e: self.remover_item_selecionado())

        # Escape para cancelar ações/focar na entrada principal
        self.root.bind('<Escape>', lambda e: self.code_entry.focus())

    def show_shortcuts_help(self):
        """Mostra janela com atalhos de teclado"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Atalhos de Teclado")
        dialog.geometry("500x600")
        dialog.transient(self.root)
        dialog.grab_set()

        # Frame principal
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # Título
        title = ttk.Label(frame, text="🎮 ATALHOS DE TECLADO",
                          font=("Arial", 16, "bold"))
        title.pack(pady=(0, 20))

        # Categorias de atalhos
        categories = [
            ("FUNÇÕES PRINCIPAIS", [
                ("F1", "Ajuda (esta tela)"),
                ("F2", "Adicionar produto"),
                ("F3", "Produto por KG"),
                ("F4", "Aplicar desconto"),
                ("F5", "Finalizar venda"),
                ("F9", "Cancelar compra"),
                ("F12", "Gerenciar produtos"),
            ]),
            ("ATALHOS COM CTRL", [
                ("Ctrl + N", "Nova venda (cancelar)"),
                ("Ctrl + F", "Finalizar venda"),
                ("Ctrl + D", "Aplicar desconto"),
                ("Ctrl + P", "Gerenciar produtos"),
                ("Ctrl + R", "Relatório de vendas"),
                ("Ctrl + Q", "Sair do sistema"),
            ]),
            ("FORMA DE PAGAMENTO (Teclas Numéricas)", [
                ("1", "Dinheiro"),
                ("2", "Cartão Débito"),
                ("3", "Cartão Crédito"),
                ("4", "PIX"),
            ]),
            ("NAVEGAÇÃO RÁPIDA", [
                ("Alt + 1", "Focar no código de barras"),
                ("Alt + 2", "Focar no valor recebido"),
                ("Esc", "Voltar para entrada principal"),
                ("Delete", "Remover item selecionado"),
                ("Enter", "Calcular troco (no campo recebido)"),
            ]),
        ]

        for category, shortcuts in categories:
            # Cabeçalho da categoria
            cat_label = ttk.Label(frame, text=category,
                                  font=("Arial", 12, "bold"),
                                  foreground="#2C3E50")
            cat_label.pack(anchor=tk.W, pady=(15, 5))

            # Lista de atalhos
            for shortcut, description in shortcuts:
                shortcut_frame = ttk.Frame(frame)
                shortcut_frame.pack(fill=tk.X, pady=2)

                shortcut_label = ttk.Label(shortcut_frame, text=shortcut,
                                           font=("Consolas", 10, "bold"),
                                           width=15, anchor=tk.W)
                shortcut_label.pack(side=tk.LEFT)

                desc_label = ttk.Label(shortcut_frame, text=description,
                                       font=("Arial", 10))
                desc_label.pack(side=tk.LEFT, padx=(10, 0))

        # Botão fechar
        ttk.Button(frame, text="Fechar (ESC)", command=dialog.destroy,
                   style="Accent.TButton").pack(pady=(20, 0))

        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def focus_payment_method(self, method):
        """Foca em uma forma de pagamento específica"""
        self.payment_method.set(method)

    def set_payment_method(self, method):
        """Define a forma de pagamento com tecla numérica"""
        self.payment_method.set(method)
        self.atualizar_lista()

        # Feedback visual
        methods = {
            'dinheiro': 'Dinheiro',
            'debito': 'Cartão Débito',
            'credito': 'Cartão Crédito',
            'pix': 'PIX'
        }
        self.info_text.insert(
            tk.END, f"Forma de pagamento alterada para: {methods[method]}\n")
        self.info_text.see(tk.END)

    def remover_item_selecionado(self):
        """Remove o item selecionado do carrinho"""
        selected_item = self.tree.selection()
        if not selected_item:
            return

        # Obter índice do item
        item_index = int(self.tree.item(selected_item[0], 'values')[0]) - 1

        if 0 <= item_index < len(self.carrinho):
            produto = self.carrinho[item_index]
            if messagebox.askyesno("Confirmar", f"Remover '{produto['nome']}' do carrinho?"):
                del self.carrinho[item_index]
                self.atualizar_lista()
                self.info_text.insert(
                    tk.END, f"Produto removido: {produto['nome']}\n")
                self.info_text.see(tk.END)

    def setup_database(self):
        """Configura o banco de dados SQLite"""

        if getattr(sys, 'frozen', False):
            # ===== MODO EXECUTÁVEL (PyInstaller) =====
            app_name = "PDV_Casa_das_Massas"

            # Determinar local persistente baseado no sistema operacional
            if platform.system() == 'Windows':
                # Windows: AppData/Roaming/NomeDoApp/
                appdata_dir = os.getenv('APPDATA')
                if not appdata_dir:
                    appdata_dir = os.path.expanduser('~')  # Fallback
                app_dir = os.path.join(appdata_dir, app_name)
            else:
                # Linux/Mac: ~/.config/NomeDoApp/
                home_dir = os.path.expanduser('~')
                app_dir = os.path.join(home_dir, '.config', app_name)

            # Criar pasta do aplicativo se não existir
            os.makedirs(app_dir, exist_ok=True)

            # Caminho para o banco de dados persistente
            self.db_path = os.path.join(app_dir, 'pdv_database.db')

            # Primeira execução? Copiar banco inicial do executável
            if not os.path.exists(self.db_path):
                try:
                    # Banco original está dentro do executável (sys._MEIPASS)
                    source_db = os.path.join(sys._MEIPASS, 'pdv_database.db')
                    if os.path.exists(source_db):
                        shutil.copy2(source_db, self.db_path)
                        print(f"✅ Banco inicial copiado para: {self.db_path}")
                    else:
                        print("⚠️ Banco inicial não encontrado no executável")
                        # Continuar mesmo assim - tabelas serão criadas abaixo
                except Exception as e:
                    print(f"⚠️ Erro ao copiar banco inicial: {e}")
                    # Continuar - o banco será criado vazio abaixo
        else:
            # ===== MODO DESENVOLVIMENTO =====
            self.db_path = os.path.join(
                os.path.dirname(__file__), 'pdv_database.db')

        # ===== CONEXÃO E CRIAÇÃO DE TABELAS =====
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            print(f"📁 Banco conectado: {self.db_path}")

            # Criar tabela de produtos
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS produtos (
                    codigo_barras TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    preco REAL NOT NULL,
                    validade TEXT,
                    codigo_sistema INTEGER
                )
            ''')

            # Criar tabela de vendas
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS vendas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT NOT NULL,
                    total REAL NOT NULL,
                    forma_pagamento TEXT NOT NULL,
                    troco REAL,
                    itens TEXT NOT NULL
                )
            ''')

            # Criar tabela de transações diárias
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS transacoes_diarias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    total_vendas REAL NOT NULL,
                    total_dinheiro REAL NOT NULL,
                    total_cartao REAL NOT NULL,
                    total_pix REAL NOT NULL
                )
            ''')

            # Verificar e adicionar a coluna 'cpf' na tabela 'vendas', se não existir
            self.cursor.execute("PRAGMA table_info(vendas)")
            colunas = [coluna[1] for coluna in self.cursor.fetchall()]
            if 'cpf' not in colunas:
                self.cursor.execute("ALTER TABLE vendas ADD COLUMN cpf TEXT")

            self.conn.commit()
            print("✅ Tabelas configuradas com sucesso")

        except sqlite3.Error as e:
            print(f"❌ Erro no banco de dados: {e}")
            raise

    def decodificar_codigo_barras(self, codigo):
        """Decodifica o código de barras seguindo a lógica do sistema"""
        codigo_str = str(codigo).strip()

        # Caso especial: PRODUTO POR KG (7 dígitos)
        if codigo_str == '2000000':
            return {
                'codigo': codigo_str,
                'nome': 'PRODUTO POR KG',
                'preco': 0.01,  # Preço base por kg
                'peso_necessario': True
            }

        # Verificar se é um código de balança (13 dígitos)
        if len(codigo_str) == 13 and codigo_str[:7].isdigit():
            identificacao = codigo_str[:7]

            # Buscar produto pela identificação
            self.cursor.execute(
                "SELECT * FROM produtos WHERE codigo_barras LIKE ?",
                (f"{identificacao}%",)
            )
            produto = self.cursor.fetchone()

            if produto:
                # Extrair preço dos últimos 6 dígitos como valor com duas casas decimais
                # 2003400036370
                # Últimos 6 dígitos são o valor em centavos
                valor_centavos = int(codigo_str[-6:-1])
                valor = float(valor_centavos) / 100.0

                preco_por_kg = produto[2]  # Preço por kg do banco de dados
                if preco_por_kg > 0:
                    peso_kg = valor / preco_por_kg  # Calcula o peso em kg
                    peso_g = int(peso_kg * 1000)  # Converte para gramas
                else:
                    peso_g = 0  # Caso o preço por kg seja inválido

                return {
                    'codigo': codigo_str,
                    'nome': produto[1],
                    'preco': valor,
                    'peso': peso_g,  # Adiciona o peso calculado
                    'peso_necessario': False
                }

        # Buscar produto exato no banco de dados
        self.cursor.execute(
            "SELECT * FROM produtos WHERE codigo_barras = ?",
            (codigo_str,)
        )
        produto = self.cursor.fetchone()

        if produto:
            return {
                'codigo': produto[0],
                'nome': produto[1],
                'preco': produto[2],
                'peso_necessario': False
            }

        return None

    def setup_gui(self):
        """Configura a interface gráfica"""
        # Substituir Tk por TTKBootstrap para aplicar temas
        # Exemplo de tema: flatly, darkly, cyborg, etc.
        self.root = ttkb.Window(themename="flatly")
        self.root.title("PDV Casa das Massas - Sistema de Caixa")
        # Aumentado para acomodar elementos maiores
        self.root.geometry("1300x900")
        icon_path = resource_path('logo_casa_das_massas.ico')
        # Adicionar um ícone (certifique-se de ter o arquivo `icon.ico`)
        self.root.iconbitmap(icon_path)

        # Inicializar a variável CPF após a criação da janela principal
        self.cpf_var = tk.StringVar()

        # Configurar estilo
        self.setup_styles()

        # Frame principal
        main_frame = ttkb.Frame(self.root, padding=10)
        main_frame.pack(fill=BOTH, expand=True)

        # Cabeçalho
        header_frame = ttkb.Frame(main_frame, bootstyle=PRIMARY)
        header_frame.pack(fill=X, pady=(0, 10))

        # Logo da loja
        # Certifique-se de que o arquivo está no mesmo diretório.
        logo_image = Image.open(resource_path('logo_casa_das_massas.png'))
        logo_image = logo_image.resize((100, 100), Image.Resampling.LANCZOS)
        self.logo_photo = ImageTk.PhotoImage(logo_image)
        logo_label = ttkb.Label(header_frame, image=self.logo_photo)
        logo_label.pack(side=LEFT, padx=(0, 20))

        # Título
        title_label = ttkb.Label(
            header_frame,
            text="Casa das Massas",
            font=("Arial", 28, "bold"),
            foreground="#FFFFFF",
            bootstyle=INVERSE
        )
        title_label.pack(side=LEFT, padx=(0, 20))

        # Data e hora
        self.time_label = ttkb.Label(
            header_frame,
            font=("Arial", 14),  # Aumentado
            foreground="#FFFFFF",
            bootstyle=INVERSE
        )
        self.time_label.pack(side=RIGHT)
        self.update_time()

        # Botões no cabeçalho
        button_frame_header = ttkb.Frame(header_frame, bootstyle=PRIMARY)  # Adicione bootstyle=PRIMARY
        button_frame_header.pack(side=RIGHT, padx=(0, 20))

        manage_button = ttkb.Button(
            button_frame_header,
            text="Gerenciar Produtos (F12)",
            command=self.gerenciar_produtos,
            bootstyle="info",  # Mude para "light" para contraste no fundo azul
            width=25
        )
        manage_button.pack(side=LEFT, padx=(0, 10))

        report_button = ttkb.Button(
            button_frame_header,
            text="Relatório de Vendas (Ctrl+R)",
            command=self.exibir_relatorio_vendas,
            bootstyle="success",  # Mude para "light" para contraste no fundo azul
            width=25
        )
        report_button.pack(side=LEFT)

        # Área principal dividida
        paned = ttkb.Panedwindow(main_frame, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True)

        # Painel esquerdo - Produtos
        left_frame = ttkb.Frame(paned, padding=10)
        paned.add(left_frame, weight=2)

        # Entrada do código de barras
        entry_frame = ttkb.Labelframe(
            # Padding aumentado
            left_frame, text="Leitor de Código de Barras", padding=15, bootstyle=PRIMARY)
        entry_frame.pack(fill=X, pady=(0, 10))

        ttkb.Label(entry_frame, text="Código:", font=(
            "Arial", 14)).pack(side=LEFT)  # Fonte aumentada
        self.code_entry = ttkb.Entry(entry_frame, font=(
            "Arial", 18), width=30)  # Fonte e tamanho aumentados
        self.code_entry.pack(side=LEFT, fill=X, expand=True, padx=(10, 5))
        self.code_entry.bind('<Return>', self.adicionar_produto)

        # Frame para botões de ação
        action_buttons_frame = ttkb.Frame(entry_frame)
        action_buttons_frame.pack(side=LEFT, padx=(5, 0))

        ttkb.Button(
            action_buttons_frame,
            text="Adicionar (F2)",
            command=self.adicionar_produto,
            bootstyle=SUCCESS,
            width=20  # Largura aumentada
        ).pack(side=LEFT, padx=(0, 5))

        ttkb.Button(
            action_buttons_frame,
            text="Produto por KG (F3)",
            command=self.adicionar_produto_kg,
            bootstyle=INFO,
            width=20  # Largura aumentada
        ).pack(side=LEFT)

        # Lista de produtos da compra
        list_frame = ttkb.Labelframe(
            left_frame, text="Itens da Compra", padding=10, bootstyle=PRIMARY)  # Padding aumentado
        list_frame.pack(fill=BOTH, expand=True)

        # Treeview para produtos
        columns = ('item', 'nome', 'qtd', 'peso', 'preco', 'total')
        self.tree = ttkb.Treeview(
            list_frame, columns=columns, show='headings', height=20, bootstyle=INFO)  # Altura aumentada

        # Configurar colunas com fontes maiores
        style = ttk.Style()
        style.configure("Treeview", font=("Arial", 12),
                        rowheight=35)  # Fonte e altura aumentadas

        self.tree.heading('item', text='Item')
        self.tree.heading('nome', text='Produto')
        self.tree.heading('qtd', text='Qtd')
        self.tree.heading('peso', text='Peso')
        self.tree.heading('preco', text='Preço Unit.')
        self.tree.heading('total', text='Total')

        self.tree.column('item', width=70, anchor=CENTER)  # Largura aumentada
        self.tree.column('nome', width=350)  # Largura aumentada
        self.tree.column('qtd', width=80, anchor=CENTER)  # Largura aumentada
        self.tree.column('peso', width=100, anchor=E)  # Largura aumentada
        self.tree.column('preco', width=120, anchor=E)  # Largura aumentada
        self.tree.column('total', width=120, anchor=E)  # Largura aumentada

        scrollbar = ttkb.Scrollbar(
            list_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # Painel direito - Pagamento e Totais
        right_frame = ttkb.Frame(paned, padding=10)
        paned.add(right_frame, weight=1)

        # Totais
        totals_frame = ttkb.Labelframe(
            right_frame, text="Totais", padding=20, bootstyle=PRIMARY)  # Padding aumentado
        totals_frame.pack(fill=X, pady=(0, 15))  # Espaço aumentado

        self.subtotal_var = tk.StringVar(value="R$ 0,00")
        self.desconto_var = tk.StringVar(value="R$ 0,00")
        self.total_var = tk.StringVar(value="R$ 0,00")

        ttkb.Label(totals_frame, text="Subtotal:", font=("Arial", 14)).grid(
            row=0, column=0, sticky=W, pady=8)  # Fonte aumentada
        subtotal_label = ttkb.Label(totals_frame, textvariable=self.subtotal_var,
                                    # Fonte aumentada
                                    font=("Arial", 16, "bold"),
                                    foreground="#2C3E50")
        subtotal_label.grid(row=0, column=1, sticky=E, pady=8)

        ttkb.Label(totals_frame, text="Desconto:", font=("Arial", 14)).grid(
            row=1, column=0, sticky=W, pady=8)  # Fonte aumentada
        desconto_label = ttkb.Label(totals_frame, textvariable=self.desconto_var,
                                    font=("Arial", 14),  # Fonte aumentada
                                    foreground="#E74C3C")
        desconto_label.grid(row=1, column=1, sticky=E, pady=8)

        ttkb.Separator(totals_frame, orient=HORIZONTAL).grid(
            row=2, column=0, columnspan=2, sticky=EW, pady=15)  # Espaço aumentado

        ttkb.Label(totals_frame, text="TOTAL:", font=("Arial", 18, "bold")).grid(
            row=3, column=0, sticky=W, pady=10)  # Fonte aumentada
        total_label = ttkb.Label(totals_frame, textvariable=self.total_var,
                                 # Fonte aumentada significativamente
                                 font=("Arial", 24, "bold"),
                                 foreground="#27AE60")
        total_label.grid(row=3, column=1, sticky=E, pady=10)

        # Forma de pagamento
        payment_frame = ttkb.Labelframe(
            right_frame, text="Forma de Pagamento", padding=20, bootstyle=PRIMARY)  # Padding aumentado
        payment_frame.pack(fill=X, pady=(0, 15))  # Espaço aumentado

        self.payment_method = tk.StringVar(value="dinheiro")

        # Botões de pagamento maiores
        payment_buttons_frame = ttkb.Frame(payment_frame)
        payment_buttons_frame.pack(fill=X)

        # Criar botões maiores para formas de pagamento
        dinheiro_btn = ttkb.Radiobutton(
            payment_buttons_frame,
            text="1 - Dinheiro",
            variable=self.payment_method,
            value="dinheiro",
            bootstyle="success-toolbutton",
            width=20  # Largura aumentada
        )
        dinheiro_btn.pack(anchor=W, pady=8, fill=X)  # Espaço aumentado

        debito_btn = ttkb.Radiobutton(
            payment_buttons_frame,
            text="2 - Cartão Débito",
            variable=self.payment_method,
            value="debito",
            bootstyle="info-toolbutton",
            width=20  # Largura aumentada
        )
        debito_btn.pack(anchor=W, pady=8, fill=X)  # Espaço aumentado

        credito_btn = ttkb.Radiobutton(
            payment_buttons_frame,
            text="3 - Cartão Crédito",
            variable=self.payment_method,
            value="credito",
            bootstyle="warning-toolbutton",
            width=20  # Largura aumentada
        )
        credito_btn.pack(anchor=W, pady=8, fill=X)  # Espaço aumentado

        pix_btn = ttkb.Radiobutton(
            payment_buttons_frame,
            text="4 - PIX",
            variable=self.payment_method,
            value="pix",
            bootstyle="primary-toolbutton",
            width=20  # Largura aumentada
        )
        pix_btn.pack(anchor=W, pady=8, fill=X)  # Espaço aumentado

        # Valor recebido (para dinheiro)
        self.received_frame = ttkb.Frame(payment_frame)
        self.received_frame.pack(fill=X, pady=(15, 0))  # Espaço aumentado

        ttkb.Label(self.received_frame, text="Recebido:", font=(
            "Arial", 14)).pack(side=LEFT)  # Fonte aumentada
        self.received_entry = ttkb.Entry(
            # Fonte aumentada
            self.received_frame, width=15, font=("Arial", 14))
        self.received_entry.pack(side=LEFT, padx=(10, 10))
        ttkb.Button(
            self.received_frame,
            text="Calcular Troco (Enter)",
            command=self.calcular_troco,
            bootstyle=INFO,
            width=20  # Largura aumentada
        ).pack(side=LEFT)

        self.troco_var = tk.StringVar(value="Troco: R$ 0,00")
        troco_label = ttkb.Label(payment_frame, textvariable=self.troco_var,
                                 font=("Arial", 14, "bold"),  # Fonte aumentada
                                 foreground="#2980B9")
        troco_label.pack(pady=(10, 0))

        # Adicionar entrada para CPF na nota fiscal
        cpf_frame = ttkb.Frame(payment_frame)
        cpf_frame.pack(fill=X, pady=(15, 0))  # Espaço aumentado

        ttkb.Label(cpf_frame, text="CPF na Nota:", font=("Arial", 14)).pack(
            anchor=W, pady=(0, 5))  # Fonte aumentada
        cpf_entry = ttkb.Entry(cpf_frame, textvariable=self.cpf_var, width=25, font=(
            "Arial", 14))  # Fonte aumentada
        cpf_entry.pack(anchor=W, fill=X)

        # Botões de ação
        buttons_frame = ttkb.Frame(right_frame, padding=10)
        buttons_frame.pack(fill=X, pady=(10, 0))

        # Botões maiores com fontes maiores
        cancel_button = ttkb.Button(
            buttons_frame,
            text="Cancelar Compra (F9)",
            command=self.cancelar_compra,
            bootstyle=DANGER,
            width=25  # Largura aumentada
        )
        cancel_button.pack(fill=X, pady=8)  # Espaço aumentado

        finalizar_button = ttkb.Button(
            buttons_frame,
            text="Finalizar Venda (F5)",
            command=self.finalizar_venda,
            bootstyle=SUCCESS,
            width=25  # Largura aumentada
        )
        finalizar_button.pack(fill=X, pady=8)  # Espaço aumentado

        # Área de informações
        info_frame = ttkb.Labelframe(
            right_frame, text="Informações e Log", padding=10, bootstyle=PRIMARY)
        info_frame.pack(fill=BOTH, expand=True,
                        pady=(15, 0))  # Espaço aumentado

        self.info_text = scrolledtext.ScrolledText(
            info_frame, height=12, font=("Consolas", 11))  # Fonte aumentada
        self.info_text.pack(fill=BOTH, expand=True)

        # Inicializar variáveis
        self.carrinho = []
        self.subtotal = Decimal('0.00')
        self.desconto = Decimal('0.00')
        self.total = Decimal('0.00')
        # Focar na entrada do código
        self.code_entry.focus()
        try:
            logo_image = Image.open(resource_path('logo_casa_das_massas.png'))
            logo_image = logo_image.resize(
                (100, 100), Image.Resampling.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_image)
            logo_label = ttk.Label(header_frame, image=self.logo_photo)
            logo_label.pack(side=tk.LEFT, padx=(0, 20))
        except Exception as e:
            print(f"Erro ao carregar logo: {e}")

    def setup_styles(self):
        """Configura os estilos da interface"""
        style = ttk.Style()

        # Configurações de tema
        style.theme_use('clam')

        # Cores principais
        primary_color = '#3498DB'
        success_color = '#2ECC71'
        danger_color = '#E74C3C'
        warning_color = '#F39C12'

        style.configure('Info.TButton', 
                   background='#3498DB', 
                   foreground='white',
                   font=('Arial', 11, 'bold'),
                   padding=8)
        
        style.map('Info.TButton',
                background=[('active', '#2980B9'), ('disabled', '#BDC3C7')])
        
        style.configure('Warning.TButton', 
                    background='#F39C12', 
                    foreground='white',
                    font=('Arial', 11, 'bold'),
                    padding=8)
        
        style.map('Warning.TButton',
                background=[('active', '#D68910'), ('disabled', '#BDC3C7')])
        # Configurar estilos para botões maiores
        style.configure('Accent.TButton',
                        background=primary_color,
                        foreground='white',
                        font=('Arial', 12, 'bold'),  # Fonte maior
                        padding=10)  # Padding maior

        style.map('Accent.TButton',
                  background=[('active', '#2980B9'), ('disabled', '#BDC3C7')])

        style.configure('Success.TButton',
                        background=success_color,
                        foreground='white',
                        font=('Arial', 12, 'bold'),  # Fonte maior
                        padding=10)  # Padding maior

        style.map('Success.TButton',
                  background=[('active', '#27AE60'), ('disabled', '#BDC3C7')])

        style.configure('Danger.TButton',
                        background=danger_color,
                        foreground='white',
                        font=('Arial', 12, 'bold'),  # Fonte maior
                        padding=10)  # Padding maior

        style.map('Danger.TButton',
                  background=[('active', '#C0392B'), ('disabled', '#BDC3C7')])

        style.configure('Secondary.TButton',
                        background=warning_color,
                        foreground='white',
                        font=('Arial', 12, 'bold'),  # Fonte maior
                        padding=10)  # Padding maior

        style.map('Secondary.TButton',
                  background=[('active', '#D68910'), ('disabled', '#BDC3C7')])

        # Estilo para Treeview com fonte maior
        style.configure("Treeview",
                        font=('Arial', 12),  # Fonte maior
                        rowheight=35,  # Altura maior
                        background='white',
                        fieldbackground='white')

        style.configure("Treeview.Heading",
                        font=('Arial', 13, 'bold'),  # Fonte maior
                        background='#3498db',
                        foreground='white',
                        padding=8)  # Padding maior

        # Estilo para Radio buttons maiores
        style.configure('Toolbutton',
                        font=('Arial', 12),  # Fonte maior
                        padding=8)  # Padding maior

    def update_time(self):
        """Atualiza a data e hora na interface"""
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.time_label.config(text=now)
        self.root.after(1000, self.update_time)

    def adicionar_produto(self, event=None):
        """Adiciona produto ao carrinho"""
        entrada = self.code_entry.get().strip()

        if not entrada:
            messagebox.showwarning(
                "Atenção", "Digite um código de barras ou nome do produto!")
            return

        self.code_entry.delete(0, tk.END)

        # Verificar se é um código de barras ou nome
        if entrada.isdigit():
            produto = self.decodificar_codigo_barras(entrada)
            if produto:
                self.adicionar_produto_ao_carrinho(produto)
                self.info_text.insert(
                    tk.END, f"Produto adicionado: {produto['nome']} - R$ {produto['preco']:.2f}\n")
                self.info_text.see(tk.END)
            else:
                messagebox.showerror("Erro", "Produto não encontrado!")
            self.code_entry.focus()
        else:
            produtos = self.buscar_produtos_por_nome(entrada)
            if produtos:
                # A janela "Selecione um Produto" e modal e cuida do
                # proprio foco (Enter/Esc/duplo-clique -> selecionar ou
                # cancelar). Focar de volta no code_entry AQUI tira o
                # teclado da janela assim que ela abre: Esc e Enter passam
                # a cair no `self.root.bind('<Escape>', ...)` e no
                # `code_entry` em vez de fechar a janela de selecao.
                self.exibir_lista_produtos(produtos)
            else:
                messagebox.showerror(
                    "Erro", "Nenhum produto encontrado com esse nome!")
                self.code_entry.focus()

    def buscar_produtos_por_nome(self, nome):
        """Busca produtos pelo nome no banco de dados"""
        nome = f"%{nome.lower()}%"
        self.cursor.execute(
            "SELECT codigo_barras, nome, preco FROM produtos WHERE LOWER(nome) LIKE ?",
            (nome,)
        )
        return self.cursor.fetchall()

    def exibir_lista_produtos(self, produtos):
        """Exibe uma janela com a lista de produtos encontrados"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Selecione um Produto")
        dialog.geometry("600x500")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        # Frame principal
        main_frame = ttk.Frame(dialog, padding=15)  # Padding aumentado
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Label informativo
        info_label = ttk.Label(
            main_frame,
            text=f"Encontrados {len(produtos)} produtos. Selecione um:",
            font=("Arial", 12, "bold")  # Fonte aumentada
        )
        info_label.pack(anchor=tk.W, pady=(0, 15))  # Espaço aumentado

        # Frame para a lista de produtos
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True,
                        pady=(0, 15))  # Espaço aumentado

        # Treeview para exibir os produtos com fonte maior
        columns = ('codigo', 'nome', 'preco')
        tree = ttk.Treeview(list_frame, columns=columns,
                            show='headings', height=15)

        # Configurar estilo da treeview
        style = ttk.Style()
        style.configure("List.Treeview", font=('Arial', 11))  # Fonte maior
        style.configure("List.Treeview.Heading", font=(
            'Arial', 12, 'bold'))  # Fonte maior

        tree.heading('codigo', text='Código')
        tree.heading('nome', text='Nome')
        tree.heading('preco', text='Preço')

        tree.column('codigo', width=120, anchor=tk.CENTER)  # Largura aumentada
        tree.column('nome', width=300)  # Largura aumentada
        tree.column('preco', width=120, anchor=tk.E)  # Largura aumentada

        # Scrollbar
        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        # Adicionar produtos à lista
        for produto in produtos:
            tree.insert('', 'end', values=(
                produto[0], produto[1], f"R$ {produto[2]:.2f}".replace('.', ',')))

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Adicionar evento de duplo-clique
        def on_double_click(event):
            selecionar_produto()

        tree.bind('<Double-Button-1>', on_double_click)

        # Funções
        def selecionar_produto():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning("Atenção", "Selecione um produto!")
                return

            produto_selecionado = tree.item(selected_item[0], 'values')
            try:
                preco_str = produto_selecionado[2].replace(
                    'R$', '').replace(',', '.').strip()
                produto = {
                    'codigo': produto_selecionado[0],
                    'nome': produto_selecionado[1],
                    'preco': float(preco_str),
                    'peso_necessario': False
                }
                self.adicionar_produto_ao_carrinho(produto)
                self.info_text.insert(
                    tk.END, f"Produto adicionado: {produto['nome']} - R$ {produto['preco']:.2f}\n")
                self.info_text.see(tk.END)
                dialog.destroy()
                self.code_entry.focus()
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao processar produto: {e}")

        def cancelar():
            dialog.destroy()
            self.code_entry.focus()

        # Botões de ação maiores
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(
            button_frame,
            text="Cancelar (ESC)",
            command=cancelar,
            style="Danger.TButton",
            width=20  # Largura aumentada
        ).pack(side=tk.LEFT, padx=(0, 15))  # Espaço aumentado

        ttk.Button(
            button_frame,
            text="Selecionar (ENTER)",
            command=selecionar_produto,
            style="Success.TButton",
            width=20  # Largura aumentada
        ).pack(side=tk.RIGHT)

        # Adicionar evento Enter para selecionar
        dialog.bind('<Return>', lambda e: selecionar_produto())

        # Adicionar evento Escape para cancelar
        dialog.bind('<Escape>', lambda e: cancelar())

        # Selecionar o primeiro item da lista e manter o foco na arvore:
        # e o que faz as setas Cima/Baixo trocarem a linha destacada. Um
        # `dialog.focus_set()` aqui (como havia antes) tira o foco da
        # arvore para o Toplevel e quebra a navegacao por seta -- Enter e
        # Esc continuam funcionando do mesmo jeito, porque o Treeview nao
        # tem binding proprio para essas teclas e elas sobem ate os binds
        # do `dialog` de qualquer forma.
        if tree.get_children():
            tree.selection_set(tree.get_children()[0])
            tree.focus_set()
            tree.focus(tree.get_children()[0])
        else:
            tree.focus_set()

    def adicionar_produto_ao_carrinho(self, produto):
        """Adiciona o produto ao carrinho"""
        # Verificar se produto já está no carrinho
        for item in self.carrinho:
            if item['codigo'] == produto['codigo']:
                item['quantidade'] += 1
                item['total'] = Decimal(
                    str(item['quantidade'])) * Decimal(str(item['preco']))
                self.atualizar_lista()
                return

        # Adicionar novo produto
        produto['quantidade'] = 1
        produto['total'] = Decimal(str(produto['preco']))
        self.carrinho.append(produto)
        self.atualizar_lista()

    def adicionar_produto_kg(self):
        """Adiciona produto vendido por quilo"""
        produto = {
            'codigo': '2000000',
            'nome': 'PRODUTO POR KG',
            'preco': 0.01,
            'peso_necessario': True
        }
        self.adicionar_produto_kg_personalizado(produto)

    def adicionar_produto_kg_personalizado(self, produto):
        """Abre janela para inserir peso e preço do produto por kg"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Produto por Quilo")
        dialog.geometry("400x350")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        main_frame = ttk.Frame(dialog, padding=20)  # Padding aumentado
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Produto: PRODUTO POR KG",
                  # Fonte aumentada
                  font=("Arial", 14, "bold")).pack(pady=(0, 20))

        ttk.Label(main_frame, text="Peso (gramas):", font=(
            "Arial", 12)).pack(anchor=tk.W)  # Fonte aumentada
        peso_entry = ttk.Entry(main_frame, font=(
            "Arial", 14), width=20)  # Fonte aumentada
        peso_entry.pack(pady=(5, 15), fill=tk.X)
        peso_entry.focus()

        ttk.Label(main_frame, text="Preço por KG (R$):", font=(
            "Arial", 12)).pack(anchor=tk.W)  # Fonte aumentada
        preco_entry = ttk.Entry(main_frame, font=(
            "Arial", 14), width=20)  # Fonte aumentada
        preco_entry.pack(pady=(5, 30), fill=tk.X)

        def confirmar():
            try:
                peso_g = Decimal(peso_entry.get().replace(',', '.'))
                peso_kg = peso_g / Decimal('1000')
                preco_kg = Decimal(preco_entry.get().replace(',', '.'))

                if peso_kg <= 0 or preco_kg <= 0:
                    messagebox.showerror("Erro", "Peso ou preço inválido!")
                    return

                preco_total = peso_kg * preco_kg

                produto_carrinho = {
                    'codigo': produto['codigo'],
                    'nome': f"PRODUTO POR KG ({peso_g}g)",
                    'preco': float(preco_kg.quantize(Decimal('0.01'), ROUND_HALF_UP)),
                    'quantidade': 1,
                    'peso': int(peso_g),  # Adiciona o peso ao produto
                    'total': float(preco_total.quantize(Decimal('0.01'), ROUND_HALF_UP))
                }

                self.carrinho.append(produto_carrinho)
                self.atualizar_lista()
                self.info_text.insert(
                    tk.END, f"Produto por KG adicionado: {peso_g}g - R$ {preco_total:.2f}\n")
                self.info_text.see(tk.END)
                dialog.destroy()
                self.code_entry.focus()

            except:
                messagebox.showerror("Erro", "Peso ou preço inválido!")

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="Confirmar (ENTER)", command=confirmar,
                   style="Success.TButton", width=20).pack()  # Botão maior

        dialog.bind('<Return>', lambda e: confirmar())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def atualizar_lista(self):
        """Atualiza a lista de produtos e totais"""
        # Limpar treeview
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Adicionar itens
        for i, produto in enumerate(self.carrinho, 1):
            # Exibir peso se disponível
            peso = f"{produto.get('peso', 0)}g" if 'peso' in produto and produto[
                'peso'] > 0 else '-'
            self.tree.insert('', 'end', values=(
                i,
                # Caracteres aumentados
                produto['nome'][:35] +
                ('...' if len(produto['nome']) > 35 else ''),
                produto['quantidade'],
                peso,
                f"R$ {produto['preco']:.2f}".replace('.', ','),
                f"R$ {produto['total']:.2f}".replace('.', ',')
            ))

        # Calcular totais
        self.subtotal = sum(Decimal(str(item['total']))
                            for item in self.carrinho)
        self.total = self.subtotal - self.desconto

        # Atualizar display
        self.subtotal_var.set(f"R$ {self.subtotal:.2f}".replace('.', ','))
        self.desconto_var.set(f"R$ {self.desconto:.2f}".replace('.', ','))
        self.total_var.set(f"R$ {self.total:.2f}".replace('.', ','))

        # Mostrar/ocultar entrada para dinheiro
        if self.payment_method.get() == "dinheiro":
            self.received_frame.pack(fill=tk.X, pady=(15, 0))
        else:
            self.received_frame.pack_forget()
            self.troco_var.set("Troco: R$ 0,00")

    def calcular_troco(self):
        """Calcula o troco para pagamento em dinheiro"""
        try:
            recebido = Decimal(self.received_entry.get().replace(',', '.'))
            troco = recebido - self.total

            if troco < 0:
                messagebox.showwarning("Atenção", "Valor insuficiente!")
                self.troco_var.set(
                    f"Faltam: R$ {abs(troco):.2f}".replace('.', ','))
                self.info_text.insert(
                    tk.END, f"Valor insuficiente! Faltam: R$ {abs(troco):.2f}\n")
                self.info_text.see(tk.END)
            else:
                self.troco_var.set(f"Troco: R$ {troco:.2f}".replace('.', ','))
                self.info_text.insert(
                    tk.END, f"Troco calculado: R$ {troco:.2f}\n")
                self.info_text.see(tk.END)

        except:
            messagebox.showerror("Erro", "Valor inválido!")

    def aplicar_desconto(self):
        """Aplica desconto na compra"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Aplicar Desconto")
        dialog.geometry("400x250")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        main_frame = ttk.Frame(dialog, padding=20)  # Padding aumentado
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Valor do Desconto:",
                  font=("Arial", 14)).pack(pady=(0, 15))  # Fonte aumentada

        desconto_entry = ttk.Entry(main_frame, font=(
            "Arial", 16), width=20)  # Fonte aumentada
        desconto_entry.pack(pady=(0, 20), fill=tk.X)
        desconto_entry.insert(0, f"{self.desconto:.2f}".replace('.', ','))
        desconto_entry.select_range(0, tk.END)
        desconto_entry.focus()

        def confirmar():
            try:
                valor = Decimal(desconto_entry.get().replace(',', '.'))

                if valor < 0 or valor > self.subtotal:
                    messagebox.showerror("Erro", "Valor de desconto inválido!")
                    return

                self.desconto = valor
                self.atualizar_lista()
                self.info_text.insert(
                    tk.END, f"Desconto aplicado: R$ {valor:.2f}\n")
                self.info_text.see(tk.END)
                dialog.destroy()

            except:
                messagebox.showerror("Erro", "Valor inválido!")

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="Aplicar (ENTER)", command=confirmar,
                   style="Success.TButton", width=20).pack()  # Botão maior

        dialog.bind('<Return>', lambda e: confirmar())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def finalizar_venda(self):
        """Finaliza a venda atual"""
        if not self.carrinho:
            messagebox.showwarning("Atenção", "Nenhum produto no carrinho!")
            return

        forma_pagamento = self.payment_method.get()

        if forma_pagamento == "dinheiro":
            try:
                recebido = Decimal(self.received_entry.get().replace(',', '.'))
                if recebido < self.total:
                    messagebox.showwarning("Atenção", "Valor recebido insuficiente!")
                    return
            except:
                messagebox.showerror("Erro", "Valor recebido inválido!")
                return
        
        # Confirmar venda
        if not messagebox.askyesno("Confirmar", "Finalizar venda?"):
            return
        
        # Obter CPF
        cpf = self.cpf_var.get().strip()
        if cpf and not cpf.isdigit():
            messagebox.showerror("Erro", "CPF inválido! Insira apenas números.")
            return
        
        # Salvar no banco de dados
        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        itens_json = str(self.carrinho)
        troco = 0

        if forma_pagamento == "dinheiro":
            recebido = Decimal(self.received_entry.get().replace(',', '.'))
            troco = float(recebido - self.total)

        self.cursor.execute('''
            INSERT INTO vendas (data_hora, total, forma_pagamento, troco, itens)
            VALUES (?, ?, ?, ?, ?)
        ''', (data_hora, float(self.total), forma_pagamento, troco, itens_json))

        venda_id = self.cursor.lastrowid  # Obter o ID da venda recém-inserida

        # Salvar CPF na tabela de vendas (se fornecido)
        if cpf:
            self.cursor.execute('''
                UPDATE vendas
                SET cpf = ?
                WHERE id = ?
            ''', (cpf, venda_id))

        # Atualizar transações diárias
        self.atualizar_transacoes_diarias(forma_pagamento, float(self.total))

        self.conn.commit()

        # Perguntar se deseja imprimir nota fiscal
        imprimir_nf = messagebox.askyesno("Imprimir Nota Fiscal", 
                                        f"Venda finalizada com sucesso!\n\nTotal: R$ {self.total:.2f}\n\nDeseja imprimir a nota fiscal?")
        
        if imprimir_nf:
            # Gerar e imprimir NF
            self.imprimir_nota_fiscal(cpf=cpf)
            self.info_text.insert(tk.END, "📄 Nota fiscal impressa.\n")
        else:
            # Apenas salvar a NF em arquivo
            self.salvar_nf_arquivo_apenas(cpf=cpf)
            self.info_text.insert(tk.END, "💾 Nota fiscal salva (sem impressão).\n")

        # Limpar carrinho
        self.cancelar_compra()

        # Limpar o CPF após finalizar a venda
        self.cpf_var.set("")

        self.info_text.insert(tk.END, f"✅ Venda finalizada com sucesso! Total: R$ {self.total:.2f}\n")
        self.info_text.see(tk.END)

    def atualizar_transacoes_diarias(self, forma_pagamento, valor):
        """Atualiza as transações do dia no banco de dados"""
        data_atual = datetime.now().strftime("%Y-%m-%d")

        # Verificar se já existe um registro para o dia atual
        self.cursor.execute(
            "SELECT * FROM transacoes_diarias WHERE data = ?", (data_atual,))
        registro = self.cursor.fetchone()

        if registro:
            # Atualizar o registro existente
            total_vendas = registro[2] + valor
            total_dinheiro = registro[3] + \
                valor if forma_pagamento == "dinheiro" else registro[3]
            total_cartao = registro[4] + valor if forma_pagamento in [
                "credito", "debito"] else registro[4]
            total_pix = registro[5] + \
                valor if forma_pagamento == "pix" else registro[5]

            self.cursor.execute('''
                UPDATE transacoes_diarias
                SET total_vendas = ?, total_dinheiro = ?, total_cartao = ?, total_pix = ?
                WHERE data = ?
            ''', (total_vendas, total_dinheiro, total_cartao, total_pix, data_atual))
        else:
            # Inserir um novo registro para o dia
            total_dinheiro = valor if forma_pagamento == "dinheiro" else 0
            total_cartao = valor if forma_pagamento in [
                "credito", "debito"] else 0
            total_pix = valor if forma_pagamento == "pix" else 0

            self.cursor.execute('''
                INSERT INTO transacoes_diarias (data, total_vendas, total_dinheiro, total_cartao, total_pix)
                VALUES (?, ?, ?, ?, ?)
            ''', (data_atual, valor, total_dinheiro, total_cartao, total_pix))

        self.conn.commit()

    def imprimir_nota_fiscal(self, cpf=None):
        """Imprime a nota fiscal em impressora térmica"""
        try:
            # Preparar conteúdo da NF otimizado para 80 colunas
            nf_content = []
            
            # Cabeçalho com informações da empresa
            nf_content.append("=" * 48)
            nf_content.append(" " * 8 + "CASA DAS MASSAS - PINHEIRINHO")
            nf_content.append(" " * 12 + "SISTEMA DE VENDAS PDV")
            nf_content.append("=" * 48)
            
            # Informações da empresa
            nf_content.append("R. Mário Gomes Cezar, 230")
            nf_content.append("Pinheirinho, Curitiba - PR")
            nf_content.append("CEP: 81150-313")
            nf_content.append("-" * 48)
            
            # CNPJ e telefone
            nf_content.append("CNPJ: 32.055.018/0001-87")
            nf_content.append("FONE: (41) 3268-2817")
            nf_content.append("-" * 48)
            
            # Data, hora e número da venda (obter último ID)
            venda_id = self.cursor.lastrowid
            nf_content.append(f"DATA: {datetime.now().strftime('%d/%m/%Y')}")
            nf_content.append(f"HORA: {datetime.now().strftime('%H:%M:%S')}")
            nf_content.append(f"CUPOM: #{venda_id:06d}")
            nf_content.append("-" * 48)
            
            # Título dos itens
            nf_content.append("CÓD.  DESCRIÇÃO               QTD   VALOR   TOTAL")
            nf_content.append("-" * 48)
            
            # Itens da venda formatados em 4 colunas
            for produto in self.carrinho:
                # Código truncado (primeiros 6 caracteres)
                codigo = produto['codigo'][:6] if len(produto['codigo']) > 6 else produto['codigo']
                
                # Nome truncado para 22 caracteres
                nome = produto['nome'][:22] if len(produto['nome']) > 22 else produto['nome']
                
                # Quantidade formatada
                qtd = produto['quantidade']
                
                # Preço unitário
                preco = produto['preco']
                
                # Total do item
                total_item = produto['total']
                
                # Formatar linha do produto
                if 'peso' in produto and produto['peso'] > 0:
                    # Para produtos por peso
                    peso_g = produto['peso']
                    linha = f"{codigo:<6} {nome:<22} {peso_g}g"
                    nf_content.append(linha)
                    nf_content.append(f"{'':<6} {qtd:>3} x R${preco:>7.2f} R${total_item:>7.2f}")
                else:
                    # Para produtos normais
                    linha = f"{codigo:<6} {nome:<22} {qtd:>3} x R${preco:>7.2f} R${total_item:>7.2f}"
                    nf_content.append(linha)
            
            nf_content.append("-" * 48)
            
            # Totais
            nf_content.append(f"{'SUBTOTAL:':<40} R${self.subtotal:>8.2f}")
            
            if self.desconto > 0:
                nf_content.append(f"{'DESCONTO:':<40} R${self.desconto:>8.2f}")
                nf_content.append(f"{'TOTAL:':<40} R${self.total:>8.2f}")
            else:
                nf_content.append(f"{'TOTAL:':<40} R${self.total:>8.2f}")
            
            nf_content.append("-" * 48)
            
            # Forma de pagamento
            forma_pagamento = self.payment_method.get()
            pagamento_text = ""
            
            if forma_pagamento == "dinheiro":
                pagamento_text = "DINHEIRO"
                recebido = Decimal(self.received_entry.get().replace(',', '.'))
                troco = recebido - self.total
                nf_content.append(f"FORMA PGTO: {pagamento_text}")
                nf_content.append(f"RECEBIDO:   R${recebido:>8.2f}")
                nf_content.append(f"TROCO:      R${troco:>8.2f}")
            elif forma_pagamento == "debito":
                pagamento_text = "CARTÃO DÉBITO"
                nf_content.append(f"FORMA PGTO: {pagamento_text}")
            elif forma_pagamento == "credito":
                pagamento_text = "CARTÃO CRÉDITO"
                nf_content.append(f"FORMA PGTO: {pagamento_text}")
            elif forma_pagamento == "pix":
                pagamento_text = "PIX"
                nf_content.append(f"FORMA PGTO: {pagamento_text}")
            
            nf_content.append("-" * 48)
            
            # Informações do cliente
            if cpf:
                # Formatar CPF: XXX.XXX.XXX-XX
                cpf_formatado = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
                nf_content.append(f"CPF/CNPJ: {cpf_formatado}")
                nf_content.append("-" * 48)
            
            # Rodapé com mensagens
            nf_content.append(" " * 12 + "** CUPOM NÃO FISCAL **")
            nf_content.append("")
            nf_content.append(" " * 8 + "OBRIGADO PELA PREFERÊNCIA!")
            nf_content.append(" " * 4 + "VOLTE SEMPRE À CASA DAS MASSAS!")
            nf_content.append("")
            nf_content.append(" " * 4 + "(41) 3268-2817 (WhatsApp)")
            nf_content.append("=" * 48)
            nf_content.append(" " * 10 + f"*** CUPOM {venda_id:06d} ***")
            nf_content.append("=" * 48)
            
            # Mostrar pré-visualização da nota
            self.exibir_previa_nota(nf_content)
            
            # Imprimir com formatação para impressora térmica
            printer_name = win32print.GetDefaultPrinter()
            
            if platform.system() == 'Windows':
                self.imprimir_windows_termica(printer_name, nf_content)
            else:
                self.imprimir_terminal(nf_content)
            
            # Salvar em arquivo também
            self.salvar_nf_arquivo(nf_content)
            
            self.info_text.insert(tk.END, "📄 Nota fiscal impressa com sucesso!\n")
            self.info_text.see(tk.END)
            
        except Exception as e:
            print(f"Erro ao imprimir: {e}")
            self.info_text.insert(tk.END, f"⚠️ Erro ao imprimir: {e}\n")
            self.info_text.see(tk.END)
            messagebox.showwarning("Aviso", f"Erro ao imprimir: {e}\nNota salva em arquivo.")

    def imprimir_windows_termica(self, printer_name, content):
        """Imprime no Windows otimizado para impressora térmica"""
        try:
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                # Configurar para impressora térmica (80 colunas)
                printer_defaults = {"DesiredAccess": win32print.PRINTER_ALL_ACCESS}
                hjob = win32print.StartDocPrinter(hprinter, 1, ("Cupom Fiscal", None, "RAW"))
                
                try:
                    win32print.StartPagePrinter(hprinter)
                    
                    # Enviar comando para fonte condensada (se suportado)
                    # ESC M seleciona fonte condensada
                    condensed_font = b'\x1B\x4D'
                    win32print.WritePrinter(hprinter, condensed_font)
                    
                    # Centralizar cabeçalho
                    center_command = b'\x1B\x61\x01'  # ESC a 1 = centralizar
                    win32print.WritePrinter(hprinter, center_command)
                    
                    for line in content:
                        # Verificar se é linha de cabeçalho para centralizar
                        if line.startswith(" ") and "CASA DAS MASSAS" in line:
                            win32print.WritePrinter(hprinter, center_command)
                            win32print.WritePrinter(hprinter, (line.strip() + "\n").encode('utf-8'))
                        elif line.startswith(" ") and "SISTEMA DE VENDAS" in line:
                            win32print.WritePrinter(hprinter, center_command)
                            win32print.WritePrinter(hprinter, (line.strip() + "\n").encode('utf-8'))
                        elif line.startswith(" ") and "OBRIGADO" in line:
                            win32print.WritePrinter(hprinter, center_command)
                            win32print.WritePrinter(hprinter, (line.strip() + "\n").encode('utf-8'))
                        else:
                            # Alinhamento à esquerda para conteúdo normal
                            left_command = b'\x1B\x61\x00'  # ESC a 0 = alinhar à esquerda
                            win32print.WritePrinter(hprinter, left_command)
                            win32print.WritePrinter(hprinter, (line + "\n").encode('utf-8'))
                    
                    # Comando de corte de papel (se suportado)
                    # ESC m para cortar papel parcialmente
                    cut_command = b'\x1D\x56\x41\x00'
                    win32print.WritePrinter(hprinter, cut_command)
                    
                    # Avançar papel para facilitar retirada
                    feed_command = b'\n\n\n\n\n'
                    win32print.WritePrinter(hprinter, feed_command)
                    
                    win32print.EndPagePrinter(hprinter)
                finally:
                    win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
                
        except Exception as e:
            print(f"Erro na impressão térmica: {e}")
            # Fallback para impressão normal
            self.imprimir_windows(printer_name, content)

    def salvar_nf_arquivo(self, content):
        """Salva a NF em um arquivo com timestamp"""
        try:
            os.makedirs('cupons_fiscais', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            venda_id = self.cursor.lastrowid if hasattr(self.cursor, 'lastrowid') else '000000'
            filename = f"cupons_fiscais/CUPOM_{venda_id:06d}_{timestamp}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("CASA DAS MASSAS - PINHEIRINHO - CUPOM FISCAL\n")
                f.write("=" * 60 + "\n\n")
                for line in content:
                    f.write(line + "\n")
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"Arquivo gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
                f.write("=" * 60 + "\n")
                
            print(f"Cupom salvo em: {filename}")
            
        except Exception as e:
            print(f"Erro ao salvar cupom: {e}")

    def exibir_previa_nota(self, nf_content):
        """Exibe uma pré-visualização da nota fiscal formatada"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Pré-visualização do Cupom Fiscal")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        
        # Frame principal
        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Título
        ttk.Label(frame, text="PRÉ-VISUALIZAÇÃO DO CUPOM FISCAL", 
                font=("Courier", 12, "bold"),
                foreground="#2C3E50").pack(pady=(0, 15))
        
        # Área de texto para visualização com fonte de largura fixa
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        preview_text = tk.Text(text_frame, height=30, width=70, 
                            font=("Courier", 9),  # Fonte de largura fixa para alinhamento
                            bg="white", fg="black",
                            yscrollcommand=scrollbar.set,
                            relief="flat", borderwidth=0)
        preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=preview_text.yview)
        
        # Inserir conteúdo da nota com formatação
        for line in nf_content:
            # Destacar cabeçalhos e totais
            if "CASA DAS MASSAS" in line or "SISTEMA DE VENDAS" in line:
                preview_text.insert(tk.END, line + "\n", "header")
            elif "TOTAL:" in line or "SUBTOTAL:" in line or "DESCONTO:" in line:
                preview_text.insert(tk.END, line + "\n", "total")
            elif "OBRIGADO" in line or "VOLTE SEMPRE" in line:
                preview_text.insert(tk.END, line + "\n", "footer")
            elif "=" in line or "-" in line:
                preview_text.insert(tk.END, line + "\n", "separator")
            else:
                preview_text.insert(tk.END, line + "\n")
        
        # Configurar tags para formatação
        preview_text.tag_config("header", font=("Courier", 9, "bold"), 
                            foreground="#2C3E50", justify="center")
        preview_text.tag_config("total", font=("Courier", 9, "bold"), 
                            foreground="#27AE60")
        preview_text.tag_config("footer", font=("Courier", 9, "italic"), 
                            foreground="#3498DB", justify="center")
        preview_text.tag_config("separator", foreground="#7F8C8D")
        
        preview_text.config(state=tk.DISABLED)  # Apenas leitura
        
        # Botões
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(button_frame, text="Fechar (ESC)", 
                command=dialog.destroy,
                style="Secondary.TButton").pack(side=tk.RIGHT)
        
        # Atalho ESC para fechar
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
    def imprimir_windows(self, printer_name, content):
        """Imprime no Windows"""
        try:
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                hjob = win32print.StartDocPrinter(
                    hprinter, 1, ("Nota Fiscal", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hprinter)

                    for line in content:
                        win32print.WritePrinter(
                            hprinter, (line + "\n").encode('utf-8'))

                    win32print.EndPagePrinter(hprinter)
                finally:
                    win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
        except:
            # Fallback para impressão via arquivo
            self.imprimir_via_arquivo(content)

    def imprimir_terminal(self, content):
        """Imprime no terminal (para outros sistemas)"""
        print("\n" + "\n".join(content) + "\n")

    def imprimir_via_arquivo(self, content):
        """Imprime via arquivo (fallback)"""
        temp_file = tempfile.mktemp(suffix='.txt')
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(content))

        if platform.system() == 'Windows':
            os.startfile(temp_file, "print")

    def salvar_nf_arquivo(self, content):
        """Salva a NF em um arquivo"""
        os.makedirs('notas_fiscais', exist_ok=True)
        filename = f"notas_fiscais/NF_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("\n".join(content))

    def cancelar_compra(self):
        """Cancela a compra atual"""
        if self.carrinho:
            if not messagebox.askyesno("Confirmar", "Finalizar compra atual?"):
                return

        self.carrinho = []
        self.subtotal = Decimal('0.00')
        self.desconto = Decimal('0.00')
        self.total = Decimal('0.00')
        self.received_entry.delete(0, tk.END)
        self.troco_var.set("Troco: R$ 0,00")
        self.atualizar_lista()
        self.code_entry.focus()

        self.info_text.insert(
            tk.END, "🔄 Compra cancelada. Nova venda iniciada.\n")
        self.info_text.see(tk.END)

    def run(self):
        """Executa a aplicação"""
        self.root.mainloop()

    def limpar_nome_produto(self, nome):
        """Remove números do nome do produto, preservando termos importantes"""
        if not nome:
            return nome
        
        import re
        
        # Termos para preservar (com números)
        termos_com_numeros = ['4QUEIJOS', '4 QUEIJOS', '1D', '2D', '3M', '4D', '0D']
        
        # Primeiro, proteger termos específicos
        marcado = nome.upper()
        for termo in termos_com_numeros:
            if termo in marcado:
                # Substituir por placeholder
                marcado = marcado.replace(termo, f'__{termo}__')
        
        # Remover todos os outros números
        sem_numeros = re.sub(r'\d+', '', marcado)
        
        # Restaurar termos protegidos
        resultado = sem_numeros
        for termo in termos_com_numeros:
            placeholder = f'__{termo}__'
            if placeholder in resultado:
                resultado = resultado.replace(placeholder, termo)
        
        # Limpar espaços extras e formatar
        resultado = re.sub(r'\s+', ' ', resultado).strip()
        
        # Capitalizar primeira letra de cada palavra (opcional)
        # resultado = ' '.join(word.capitalize() for word in resultado.split())
        
        return resultado
    
    def importar_produtos_txt(self, filepath):
        """Importa produtos de arquivo TXT no formato específico da balança"""
        try:
            # Criar conexão local para esta thread
            local_conn = sqlite3.connect(self.db_path)
            local_cursor = local_conn.cursor()
            
            # Tentar diferentes encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            content = None
            
            for encoding in encodings:
                try:
                    with open(filepath, 'r', encoding=encoding) as file:
                        content = file.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                local_conn.close()
                return "❌ Não foi possível ler o arquivo. Encoding não suportado."
            
            lines = content.splitlines()
            
            produtos_importados = 0
            produtos_atualizados = 0
            produtos_ignorados = 0
            
            import re
            
            # Preparar listas para processamento em lote
            all_codigos_barras = []
            all_codigos_sistema = []
            produtos_data = []
            
            # Primeira passagem: coletar todos os dados
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if len(line) < 10:
                    produtos_ignorados += 1
                    continue
                
                # Ignorar caracteres especiais no final do arquivo
                if line.startswith(chr(26)):  # EOF character
                    produtos_ignorados += 1
                    continue
                
                try:
                    # Remover múltiplos espaços
                    line = re.sub(r'\s+', ' ', line)
                    
                    # Encontrar o primeiro número (código)
                    code_match = re.match(r'^(\d+)', line)
                    if not code_match:
                        produtos_ignorados += 1
                        continue
                    
                    codigo = int(code_match.group(1))
                    
                    # Remover o código do início
                    restante = line[code_match.end():].strip()
                    
                    # O próximo caractere deve ser '0'
                    if not restante.startswith('0'):
                        produtos_ignorados += 1
                        continue
                    
                    # Remover o '0' inicial
                    restante = restante[1:].strip()
                    
                    # Encontrar o preço (número com vírgula)
                    preco_match = re.search(r'(\d+,\d+)', restante)
                    if not preco_match:
                        produtos_ignorados += 1
                        continue
                    
                    preco_start = preco_match.start()
                    preco_str = preco_match.group(1)
                    preco = float(preco_str.replace(',', '.'))
                    
                    # Nome é tudo antes do preço
                    nome = restante[:preco_start].strip()
                    
                    # Tudo após o preço pode ser a validade
                    validade_part = restante[preco_start + len(preco_str):].strip()
                    validade = validade_part if validade_part else None
                    
                    # CORREÇÃO: Código de barras deve ter 7 dígitos
                    # Para código 1: "2" + "001" + "00" = "2000100" (7 dígitos)
                    # Para código 11: "2" + "011" + "00" = "2001100" (7 dígitos)
                    # Para código 153: "2" + "153" + "00" = "2015300" (7 dígitos)
                    # Usar :03d para garantir 3 dígitos com zeros à esquerda
                    codigo_barras = f"2{codigo:03d}00"
                    
                    # Verificar se o código de barras tem 7 dígitos
                    if len(codigo_barras) != 7:
                        print(f"⚠️ Código de barras inválido: {codigo_barras} (código: {codigo})")
                        produtos_ignorados += 1
                        continue
                    
                    # Coletar dados para processamento posterior
                    all_codigos_barras.append(codigo_barras)
                    all_codigos_sistema.append(str(codigo))
                    
                    produtos_data.append({
                        'codigo_barras': codigo_barras,
                        'nome': nome,
                        'preco': preco,
                        'validade': validade,
                        'codigo_sistema': codigo,
                        'line_num': line_num
                    })
                    
                except (ValueError, IndexError) as e:
                    produtos_ignorados += 1
                    print(f"Erro na linha {line_num}: '{line}' - {e}")
                    continue
                except Exception as e:
                    produtos_ignorados += 1
                    print(f"Erro inesperado na linha {line_num}: '{line}' - {e}")
                    continue
            
            # Verificar se há dados para processar
            if not produtos_data:
                local_conn.close()
                return "❌ Nenhum produto válido encontrado no arquivo."
            
            # Segunda passagem: verificar duplicatas em lote
            existing_map = {}
            if all_codigos_barras:
                # Criar consulta única para verificar todos os produtos
                # Usar UNION para evitar problemas com OR em muitas condições
                queries = []
                params = []
                
                # Para códigos de barras
                if all_codigos_barras:
                    placeholders = ','.join(['?'] * len(all_codigos_barras))
                    queries.append(f"SELECT codigo_barras, codigo_sistema FROM produtos WHERE codigo_barras IN ({placeholders})")
                    params.extend(all_codigos_barras)
                
                # Para códigos do sistema
                if all_codigos_sistema:
                    placeholders = ','.join(['?'] * len(all_codigos_sistema))
                    queries.append(f"SELECT codigo_barras, codigo_sistema FROM produtos WHERE codigo_sistema IN ({placeholders})")
                    params.extend(all_codigos_sistema)
                
                # Executar consultas
                for query in queries:
                    local_cursor.execute(query, params[:query.count('?')])
                    params = params[query.count('?'):]  # Remover parâmetros usados
                    
                    for row in local_cursor.fetchall():
                        if row[0]:  # codigo_barras
                            existing_map[row[0]] = True
                        if row[1]:  # codigo_sistema
                            existing_map[str(row[1])] = True
            
            # Terceira passagem: executar inserts/updates
            inserts_batch = []
            updates_batch = []
            
            for produto in produtos_data:
                codigo_barras = produto['codigo_barras']
                codigo_sistema_str = str(produto['codigo_sistema'])
                
                # Verificar se já existe
                exists = (codigo_barras in existing_map) or (codigo_sistema_str in existing_map)
                
                if exists:
                    # Produto já existe, vamos atualizar
                    updates_batch.append((
                        produto['nome'],
                        produto['preco'],
                        produto['validade'],
                        produto['codigo_sistema'],  # Para buscar por codigo_sistema
                        codigo_barras  # Para buscar por codigo_barras
                    ))
                    produtos_atualizados += 1
                else:
                    # Produto não existe, vamos inserir
                    inserts_batch.append((
                        codigo_barras,
                        produto['nome'],
                        produto['preco'],
                        produto['validade'],
                        produto['codigo_sistema']
                    ))
                    produtos_importados += 1
            
            # Executar INSERTs em lote
            if inserts_batch:
                insert_query = '''
                    INSERT INTO produtos (codigo_barras, nome, preco, validade, codigo_sistema)
                    VALUES (?, ?, ?, ?, ?)
                '''
                local_cursor.executemany(insert_query, inserts_batch)
                print(f"✅ Inseridos {len(inserts_batch)} novos produtos")
            
            # Executar UPDATEs em lote
            if updates_batch:
                update_query = '''
                    UPDATE produtos 
                    SET nome = ?, preco = ?, validade = ?
                    WHERE codigo_sistema = ? OR codigo_barras = ?
                '''
                local_cursor.executemany(update_query, updates_batch)
                print(f"✅ Atualizados {len(updates_batch)} produtos")
            
            # Commit final
            local_conn.commit()
            local_conn.close()
            
            # Atualizar interface na thread principal
            self._notificar_importacao_concluida(
                produtos_importados, produtos_atualizados, produtos_ignorados, len(lines)
            )
            
            # Log de resultados
            mensagem = f"""
            ✅ Importação TXT concluída!
            
            📊 Resultados:
            • Produtos importados: {produtos_importados}
            • Produtos atualizados: {produtos_atualizados}
            • Produtos ignorados: {produtos_ignorados}
            • Total de linhas processadas: {len(lines)}
            """
            
            return mensagem
            
        except FileNotFoundError:
            return "❌ Arquivo não encontrado!"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Erro detalhado: {error_details}")
            return f"❌ Erro ao importar produtos TXT: {str(e)}"

    def _notificar_importacao_concluida(self, importados, atualizados, ignorados, total):
        """Notifica a interface sobre a conclusão da importação"""
        try:
            # Usar after para executar na thread principal
            if hasattr(self, 'root'):
                self.root.after(0, lambda: self._atualizar_interface_importacao(
                    importados, atualizados, ignorados, total
                ))
        except Exception as e:
            print(f"Erro ao notificar importação: {e}")

    def _atualizar_interface_importacao(self, importados, atualizados, ignorados, total):
        """Atualiza a interface na thread principal"""
        try:
            print(f"✅ Importação concluída: {importados} novos, {atualizados} atualizados, {ignorados} ignorados")
            
            # Atualizar treeview se estiver disponível
            # Você precisa passar a referência da tree para este método
            # Ou atualizar de outra forma
            messagebox.showinfo(
                "Importação Concluída",
                f"✅ Importação concluída!\n\n"
                f"📊 Resultados:\n"
                f"• Novos produtos: {importados}\n"
                f"• Produtos atualizados: {atualizados}\n"
                f"• Linhas ignoradas: {ignorados}\n"
                f"• Total processado: {total}"
            )
            
        except Exception as e:
            print(f"Erro ao atualizar interface: {e}")

    def importar_produtos_csv(self, filepath):
        """Importa produtos de arquivo CSV"""
        try:
            # Ler o arquivo CSV
            df = pd.read_csv(filepath, encoding='utf-8')
            
            produtos_importados = 0
            produtos_atualizados = 0
            produtos_ignorados = 0
            
            # Verificar colunas necessárias
            # Se não tiver código_barras, precisamos de código_sistema para gerar
            has_codigo_sistema = 'codigo_sistema' in df.columns
            has_codigo_barras = 'codigo_barras' in df.columns
            
            if not has_codigo_barras and not has_codigo_sistema:
                return "❌ CSV precisa ter pelo menos 'codigo_barras' ou 'codigo_sistema'"
            
            if 'nome' not in df.columns or 'preco' not in df.columns:
                return "❌ Colunas obrigatórias faltando: 'nome' e 'preco' são necessárias"
            
            for index, row in df.iterrows():
                try:
                    # Extrair dados das colunas
                    nome = str(row['nome']).strip()
                    
                    # Processar preço
                    preco_str = str(row['preco']).strip()
                    # Remover R$, espaços e converter vírgula para ponto
                    preco_str = preco_str.replace('R$', '').replace(',', '.').strip()
                    
                    try:
                        preco = float(preco_str) if preco_str not in ['-', '', 'nan', 'None'] else 0.0
                    except:
                        preco = 0.0
                    
                    # Validade opcional
                    validade = str(row['validade']).strip() if 'validade' in df.columns and pd.notna(row['validade']) else None
                    
                    # Código sistema opcional
                    codigo_sistema = None
                    if has_codigo_sistema and pd.notna(row['codigo_sistema']):
                        try:
                            codigo_sistema = int(row['codigo_sistema'])
                        except:
                            codigo_sistema = None
                    
                    # Código de barras opcional
                    codigo_barras = None
                    if has_codigo_barras and pd.notna(row['codigo_barras']):
                        codigo_barras = str(row['codigo_barras']).strip()
                    
                    # Se não tiver código de barras mas tiver código do sistema, gerar
                    if not codigo_barras and codigo_sistema:
                        codigo_barras = f"2{codigo_sistema:03d}00"
                    
                    # Se não tiver nenhum código, pular
                    if not codigo_barras:
                        produtos_ignorados += 1
                        continue
                    
                    # Verificar se produto já existe
                    existing = None
                    if codigo_barras:
                        self.cursor.execute(
                            "SELECT codigo_barras FROM produtos WHERE codigo_barras = ?",
                            (codigo_barras,)
                        )
                        existing = self.cursor.fetchone()
                    elif codigo_sistema:
                        self.cursor.execute(
                            "SELECT codigo_barras FROM produtos WHERE codigo_sistema = ?",
                            (codigo_sistema,)
                        )
                        existing = self.cursor.fetchone()
                    
                    if existing:
                        # Atualizar produto existente
                        update_query = '''
                            UPDATE produtos 
                            SET nome = ?, preco = ?, validade = ?
                            WHERE codigo_barras = ?
                        '''
                        params = [nome, preco, validade, existing[0]]
                        
                        if codigo_sistema:
                            update_query = update_query.replace('validade = ?', 'validade = ?, codigo_sistema = ?')
                            params = [nome, preco, validade, codigo_sistema, existing[0]]
                        
                        self.cursor.execute(update_query, tuple(params))
                        produtos_atualizados += 1
                    else:
                        # Inserir novo produto
                        insert_query = '''
                            INSERT INTO produtos (codigo_barras, nome, preco, validade, codigo_sistema)
                            VALUES (?, ?, ?, ?, ?)
                        '''
                        params = [codigo_barras, nome, preco, validade, codigo_sistema]
                        
                        self.cursor.execute(insert_query, tuple(params))
                        produtos_importados += 1
                    
                except (ValueError, IndexError) as e:
                    produtos_ignorados += 1
                    print(f"Erro ao processar linha {index}: {row} - {e}")
                    continue
                except Exception as e:
                    produtos_ignorados += 1
                    print(f"Erro inesperado na linha {index}: {row} - {e}")
                    continue
            
            self.conn.commit()
            
            mensagem = f"""
            ✅ Importação CSV concluída!
            
            📊 Resultados:
            • Produtos importados: {produtos_importados}
            • Produtos atualizados: {produtos_atualizados}
            • Produtos ignorados: {produtos_ignorados}
            • Total de linhas processadas: {len(df)}
            """
            
            return mensagem
            
        except FileNotFoundError:
            return "❌ Arquivo não encontrado!"
        except pd.errors.EmptyDataError:
            return "❌ Arquivo CSV está vazio!"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Erro detalhado CSV: {error_details}")
            return f"❌ Erro ao importar produtos CSV: {str(e)}"
    
    def gerenciar_produtos(self):
        """Abre a janela de gerenciamento de produtos"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Gerenciar Produtos")
        dialog.geometry("1000x700")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        # Frame principal
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Frame para botões superiores
        top_button_frame = ttk.Frame(main_frame)
        top_button_frame.pack(fill=tk.X, pady=(0, 15))

        # Botão Importar Produtos TXT
        import_txt_button = ttk.Button(
            top_button_frame,
            text="📥 Importar Produtos (TXT)",
            command=lambda: self.importar_produtos_dialog(dialog, tree),
            style="Info.TButton",
            width=25
        )
        import_txt_button.pack(side=tk.LEFT, padx=(0, 10))

        # Botão Importar Produtos CSV
        import_csv_button = ttk.Button(
            top_button_frame,
            text="📥 Importar Produtos (CSV)",
            command=lambda: self.importar_produtos_dialog(dialog, tree),
            style="Info.TButton",
            width=25
        )
        import_csv_button.pack(side=tk.LEFT, padx=(0, 10))

        # Botão Exportar para CSV
        export_button = ttk.Button(
            top_button_frame,
            text="📤 Exportar para CSV",
            command=self.exportar_produtos_csv,
            style="Secondary.TButton",
            width=20
        )
        export_button.pack(side=tk.LEFT, padx=(0, 10))

        # Botão Adicionar Manual
        add_button = ttk.Button(
            top_button_frame,
            text="➕ Adicionar Produto",
            command=lambda: self.editar_produto(tree, novo=True),
            style="Success.TButton",
            width=20
        )
        add_button.pack(side=tk.RIGHT)

        # Tabela de produtos
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('codigo_barras', 'nome', 'preco', 'validade', 'codigo_sistema')
        tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=20)

        # Configurar colunas
        tree.heading('codigo_barras', text='Código de Barras')
        tree.heading('nome', text='Nome')
        tree.heading('preco', text='Preço')
        tree.heading('validade', text='Validade')
        tree.heading('codigo_sistema', text='Código Sistema')

        tree.column('codigo_barras', width=150, anchor=tk.CENTER)
        tree.column('nome', width=350)
        tree.column('preco', width=100, anchor=tk.E)
        tree.column('validade', width=100, anchor=tk.CENTER)
        tree.column('codigo_sistema', width=100, anchor=tk.CENTER)

        # Scrollbar vertical
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=v_scrollbar.set)

        # Scrollbar horizontal
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=h_scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # Frame para botões inferiores
        bottom_button_frame = ttk.Frame(main_frame)
        bottom_button_frame.pack(fill=tk.X, pady=(15, 0))

        ttk.Button(
            bottom_button_frame,
            text="✏️ Editar Produto",
            command=lambda: self.editar_produto(tree),
            style="Accent.TButton",
            width=20
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            bottom_button_frame,
            text="🗑️ Excluir Produto",
            command=lambda: self.excluir_produto(tree),
            style="Danger.TButton",
            width=20
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            bottom_button_frame,
            text="🔄 Atualizar Lista",
            command=lambda: self.carregar_produtos(tree),
            style="Secondary.TButton",
            width=20
        ).pack(side=tk.RIGHT)

        # Carregar produtos na tabela
        self.carregar_produtos(tree)

    def exportar_produtos_csv(self):
        """Exporta produtos para arquivo CSV"""
        from tkinter import filedialog
        
        # Abrir diálogo para salvar arquivo
        filepath = filedialog.asksaveasfilename(
            title="Exportar produtos para CSV",
            defaultextension=".csv",
            filetypes=[
                ("Arquivos CSV", "*.csv"),
                ("Todos os arquivos", "*.*")
            ]
        )
        
        if not filepath:
            return
        
        try:
            # Buscar todos os produtos
            self.cursor.execute("SELECT * FROM produtos ORDER BY codigo_sistema")
            produtos = self.cursor.fetchall()
            
            # Criar DataFrame
            df = pd.DataFrame(produtos, columns=['codigo_barras', 'nome', 'preco', 'validade', 'codigo_sistema'])
            
            # Exportar para CSV
            df.to_csv(filepath, index=False, encoding='utf-8')
            
            messagebox.showinfo("Sucesso", f"Produtos exportados com sucesso!\n\nTotal: {len(produtos)} produtos\nArquivo: {filepath}")
            
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar produtos: {str(e)}")

    def importar_produtos_txt_thread_safe(self, filepath):
        """Versão thread-safe do método de importação TXT"""
        # Esta função deve ser chamada apenas de threads secundárias
        # Ela retorna apenas a mensagem de resultado
        
        try:
            # Criar conexão local
            local_conn = sqlite3.connect(self.db_path)
            local_cursor = local_conn.cursor()
            
            # Tentar diferentes encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            content = None
            
            for encoding in encodings:
                try:
                    with open(filepath, 'r', encoding=encoding) as file:
                        content = file.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                local_conn.close()
                return "❌ Não foi possível ler o arquivo. Encoding não suportado."
            
            lines = content.splitlines()
            
            produtos_importados = 0
            produtos_atualizados = 0
            produtos_ignorados = 0
            
            import re
            
            # Preparar listas para processamento em lote
            all_codigos_barras = []
            all_codigos_sistema = []
            produtos_data = []
            
            # Primeira passagem: coletar todos os dados
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if len(line) < 10:
                    produtos_ignorados += 1
                    continue
                
                # Ignorar caracteres especiais no final do arquivo
                if line.startswith(chr(26)):  # EOF character
                    produtos_ignorados += 1
                    continue
                
                try:
                    # Remover múltiplos espaços
                    line = re.sub(r'\s+', ' ', line)
                    
                    # Encontrar o primeiro número (código)
                    code_match = re.match(r'^(\d+)', line)
                    if not code_match:
                        produtos_ignorados += 1
                        continue
                    
                    codigo = int(code_match.group(1))
                    
                    # Remover o código do início
                    restante = line[code_match.end():].strip()
                    
                    # O próximo caractere deve ser '0'
                    if not restante.startswith('0'):
                        produtos_ignorados += 1
                        continue
                    
                    # Remover o '0' inicial
                    restante = restante[1:].strip()
                    
                    # Encontrar o preço (número com vírgula)
                    preco_match = re.search(r'(\d+,\d+)', restante)
                    if not preco_match:
                        produtos_ignorados += 1
                        continue
                    
                    preco_start = preco_match.start()
                    preco_str = preco_match.group(1)
                    preco = float(preco_str.replace(',', '.'))
                    
                    # Nome é tudo antes do preço
                    nome = restante[:preco_start].strip()
                    
                    # Tudo após o preço pode ser a validade
                    validade_part = restante[preco_start + len(preco_str):].strip()
                    validade = validade_part if validade_part else None
                    
                    # CORREÇÃO IMPORTANTE: Gerar código de barras com 7 dígitos
                    # Para código 1: "2" + "001" + "00" = "2000100" (7 dígitos)
                    # Para código 11: "2" + "011" + "00" = "2001100" (7 dígitos)
                    # Para código 153: "2" + "153" + "00" = "215300" (6 dígitos - ERRADO!)
                    # Corrigido: código 153 -> "2" + "153" + "00" = "215300" mas queremos 7 dígitos
                    # Vamos garantir que o código interno tenha 3 dígitos:
                    # 2015300, 2008400, 2000700
                    codigo_formatado = f"{codigo:03d}"  # "001", "011", "153"
                    if len(codigo_formatado) == 1:
                        codigo_barras = f"2000{codigo_formatado}00"  # "200100"
                    elif len(codigo_formatado) == 2:
                        codigo_barras = f"200{codigo_formatado}00"   # "201100"
                    elif len(codigo_formatado) == 3:
                        codigo_barras = f"20{codigo_formatado}00"    # "215300"
                    else:
                        codigo_barras = f"20{codigo_formatado[-3:]}00"
                    
                    # DEBUG: Mostrar código gerado
                    print(f"DEBUG: Código {codigo} -> Formatado: {codigo_formatado} -> Código Barras: {codigo_barras}")
                    
                    # Coletar dados para processamento posterior
                    all_codigos_barras.append(codigo_barras)
                    all_codigos_sistema.append(str(codigo))
                    
                    produtos_data.append({
                        'codigo_barras': codigo_barras,
                        'nome': nome,
                        'preco': preco,
                        'validade': validade,
                        'codigo_sistema': codigo,
                        'line_num': line_num
                    })
                    
                except (ValueError, IndexError) as e:
                    produtos_ignorados += 1
                    print(f"Erro na linha {line_num}: '{line}' - {e}")
                    continue
                except Exception as e:
                    produtos_ignorados += 1
                    print(f"Erro inesperado na linha {line_num}: '{line}' - {e}")
                    continue
            
            # Verificar se há dados para processar
            if not produtos_data:
                local_conn.close()
                return "❌ Nenhum produto válido encontrado no arquivo."
            
            # Segunda passagem: verificar duplicatas em lote
            existing_map = {}
            if all_codigos_barras or all_codigos_sistema:
                # Verificar por código de barras
                if all_codigos_barras:
                    placeholders = ','.join(['?'] * len(all_codigos_barras))
                    query = f"SELECT codigo_barras, codigo_sistema FROM produtos WHERE codigo_barras IN ({placeholders})"
                    local_cursor.execute(query, all_codigos_barras)
                    
                    for row in local_cursor.fetchall():
                        if row[0]:  # codigo_barras
                            existing_map[row[0]] = True
                        if row[1]:  # codigo_sistema
                            existing_map[str(row[1])] = True
                
                # Verificar por código do sistema
                if all_codigos_sistema:
                    placeholders = ','.join(['?'] * len(all_codigos_sistema))
                    query = f"SELECT codigo_barras, codigo_sistema FROM produtos WHERE codigo_sistema IN ({placeholders})"
                    local_cursor.execute(query, all_codigos_sistema)
                    
                    for row in local_cursor.fetchall():
                        if row[0]:  # codigo_barras
                            existing_map[row[0]] = True
                        if row[1]:  # codigo_sistema
                            existing_map[str(row[1])] = True
            
            # Terceira passagem: executar inserts/updates
            inserts_batch = []
            updates_batch = []
            
            for produto in produtos_data:
                codigo_barras = produto['codigo_barras']
                codigo_sistema_str = str(produto['codigo_sistema'])
                
                # Verificar se já existe
                exists = (codigo_barras in existing_map) or (codigo_sistema_str in existing_map)
                
                if exists:
                    # Produto já existe, vamos atualizar
                    updates_batch.append((
                        produto['nome'],
                        produto['preco'],
                        produto['validade'],
                        produto['codigo_sistema'],  # Para buscar por codigo_sistema
                        codigo_barras  # Para buscar por codigo_barras
                    ))
                    produtos_atualizados += 1
                else:
                    # Produto não existe, vamos inserir
                    inserts_batch.append((
                        codigo_barras,
                        produto['nome'],
                        produto['preco'],
                        produto['validade'],
                        produto['codigo_sistema']
                    ))
                    produtos_importados += 1
            
            # Executar INSERTs em lote
            if inserts_batch:
                insert_query = '''
                    INSERT INTO produtos (codigo_barras, nome, preco, validade, codigo_sistema)
                    VALUES (?, ?, ?, ?, ?)
                '''
                local_cursor.executemany(insert_query, inserts_batch)
                print(f"✅ Inseridos {len(inserts_batch)} novos produtos")
            
            # Executar UPDATEs em lote
            if updates_batch:
                update_query = '''
                    UPDATE produtos 
                    SET nome = ?, preco = ?, validade = ?
                    WHERE codigo_sistema = ? OR codigo_barras = ?
                '''
                local_cursor.executemany(update_query, updates_batch)
                print(f"✅ Atualizados {len(updates_batch)} produtos")
            
            # Commit final
            local_conn.commit()
            local_conn.close()
            
            # Log de resultados
            mensagem = f"""
            ✅ Importação TXT concluída!
            
            📊 Resultados:
            • Produtos importados: {produtos_importados}
            • Produtos atualizados: {produtos_atualizados}
            • Produtos ignorados: {produtos_ignorados}
            • Total de linhas processadas: {len(lines)}
            
            🔍 Detalhes:
            • Arquivo: {os.path.basename(filepath)}
            • Tamanho do arquivo: {os.path.getsize(filepath)} bytes
            • Códigos processados: {len(produtos_data)}
            """
            
            return mensagem
            
        except FileNotFoundError:
            return "❌ Arquivo não encontrado!"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Erro detalhado: {error_details}")
            return f"❌ Erro ao importar produtos TXT: {str(e)}"
    
    def importar_produtos_dialog(self, parent_window, tree):
        """Abre diálogo para importar produtos de arquivo TXT ou CSV"""
        from tkinter import filedialog
        
        # Abrir diálogo para selecionar arquivo
        filepath = filedialog.askopenfilename(
            title="Selecionar arquivo de produtos",
            filetypes=[
                ("Arquivos de texto", "*.txt"),
                ("Arquivos CSV", "*.csv"),
                ("Todos os arquivos", "*.*")
            ]
        )
        
        if not filepath:
            return
        
        # Verificar extensão do arquivo
        if not (filepath.lower().endswith('.txt') or filepath.lower().endswith('.csv')):
            messagebox.showerror("Erro", "Por favor, selecione um arquivo .txt ou .csv")
            return
        
        # Mostrar janela de progresso
        progress_dialog = tk.Toplevel(parent_window)
        progress_dialog.title("Importando Produtos...")
        progress_dialog.geometry("400x250")
        progress_dialog.transient(parent_window)
        progress_dialog.grab_set()
        
        # Mostrar qual arquivo está sendo processado
        filename = os.path.basename(filepath)
        ttk.Label(progress_dialog, text=f"⏳ Processando: {filename}", 
                font=("Arial", 12)).pack(pady=20)
        
        ttk.Label(progress_dialog, text="Aguarde, isso pode levar alguns segundos...", 
                font=("Arial", 10)).pack()
        
        progress_bar = ttk.Progressbar(progress_dialog, mode='indeterminate', length=300)
        progress_bar.pack(pady=20)
        progress_bar.start()
        
        # Label para mostrar progresso
        progress_label = ttk.Label(progress_dialog, text="", font=("Arial", 10))
        progress_label.pack()
        
        # Forçar atualização da interface
        progress_dialog.update()
        
        def realizar_importacao():
            try:
                resultado = ""
                if filepath.lower().endswith('.txt'):
                    # Chamar o método que usa conexão local
                    resultado = self.importar_produtos_txt_thread_safe(filepath)
                elif filepath.lower().endswith('.csv'):
                    resultado = self.importar_produtos_csv_thread_safe(filepath)
                
                # Fechar janela de progresso
                progress_dialog.destroy()
                
                # Atualizar lista de produtos na interface principal
                self.root.after(0, lambda: self.carregar_produtos(tree))
                
                # Mostrar resultado
                messagebox.showinfo("Importação Concluída", resultado)
                
            except Exception as e:
                progress_dialog.destroy()
                messagebox.showerror("Erro", f"Erro ao importar produtos: {str(e)}")
        
        # Executar importação em uma thread separada
        import threading
        thread = threading.Thread(target=realizar_importacao)
        thread.daemon = True
        thread.start()

    def carregar_produtos(self, tree):
        """Carrega os produtos na tabela"""
        # Limpar tabela
        for item in tree.get_children():
            tree.delete(item)

        # Buscar produtos no banco de dados
        self.cursor.execute("SELECT * FROM produtos ORDER BY codigo_sistema")
        produtos = self.cursor.fetchall()

        # Adicionar produtos na tabela
        for produto in produtos:
            # Formatar preço
            preco_formatado = f"R$ {produto[2]:.2f}" if produto[2] else "R$ 0,00"
            
            # Tratar valores nulos
            validade = produto[3] if produto[3] and produto[3] != 'None' else "-"
            codigo_sistema = produto[4] if produto[4] and produto[4] != 'None' else "-"
            
            tree.insert('', 'end', values=(
                produto[0],  # código de barras
                produto[1],  # nome
                preco_formatado,  # preço formatado
                validade,
                codigo_sistema
            ))

    def editar_produto(self, tree, novo=False):
        """Abre a janela para adicionar ou editar um produto"""
        selected_item = tree.selection()
        if not novo and not selected_item:
            messagebox.showwarning(
                "Atenção", "Selecione um produto para editar!")
            return

        produto = tree.item(selected_item[0], 'values') if not novo else None

        dialog = tk.Toplevel(self.root)
        dialog.title("Editar Produto" if not novo else "Adicionar Produto")
        dialog.geometry("500x500")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        # Variáveis para armazenar os valores
        codigo_barras_var = tk.StringVar()
        nome_var = tk.StringVar()
        preco_var = tk.StringVar()
        validade_var = tk.StringVar()
        codigo_sistema_var = tk.StringVar()

        # Campos do formulário
        frame = ttk.Frame(dialog, padding=20)  # Padding aumentado
        frame.pack(fill=tk.BOTH, expand=True)

        # Configurar grid com pesos para responsividade
        for i in range(2):
            frame.columnconfigure(i, weight=1)

        for i in range(5):
            frame.rowconfigure(i, weight=1)

        # Código de Barras
        ttk.Label(frame, text="Código de Barras:", font=("Arial", 12)).grid(
            row=0, column=0, sticky=tk.W, pady=10)
        codigo_barras_entry = ttk.Entry(frame, width=35, font=("Arial", 12),
                                        textvariable=codigo_barras_var)
        codigo_barras_entry.grid(row=0, column=1, pady=10, sticky=tk.EW)
        
        if produto:
            codigo_barras_var.set(produto[0])
            if not novo:  # Não permitir editar código de barras existente
                codigo_barras_entry.config(state=tk.DISABLED)

        # Nome
        ttk.Label(frame, text="Nome:", font=("Arial", 12)).grid(
            row=1, column=0, sticky=tk.W, pady=10)
        nome_entry = ttk.Entry(frame, width=35, font=("Arial", 12),
                            textvariable=nome_var)
        nome_entry.grid(row=1, column=1, pady=10, sticky=tk.EW)
        if produto:
            nome_var.set(produto[1])

        # Preço
        ttk.Label(frame, text="Preço (R$):", font=("Arial", 12)).grid(
            row=2, column=0, sticky=tk.W, pady=10)
        
        # Frame para entrada de preço com botões de formatação
        preco_frame = ttk.Frame(frame)
        preco_frame.grid(row=2, column=1, pady=10, sticky=tk.EW)
        
        preco_entry = ttk.Entry(preco_frame, width=20, font=("Arial", 12),
                            textvariable=preco_var)
        preco_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Botão para inserir vírgula automaticamente
        def inserir_virgula():
            valor_atual = preco_var.get()
            if not valor_atual:
                preco_var.set("0,00")
            elif ',' not in valor_atual:
                if len(valor_atual) == 1:
                    preco_var.set(valor_atual + ",00")
                elif len(valor_atual) == 2:
                    preco_var.set(valor_atual + ",00")
                else:
                    preco_var.set(valor_atual[:-2] + "," + valor_atual[-2:])
            preco_entry.icursor(tk.END)
        
        virgula_btn = ttk.Button(preco_frame, text=",00", 
                                command=inserir_virgula, width=4)
        virgula_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        if produto:
            try:
                # Formatar preço corretamente (ex: 61.90 → 61,90)
                preco_valor = produto[2]
                if preco_valor and preco_valor != 'None' and preco_valor != '-':
                    # Remover "R$ " se existir
                    preco_valor = preco_valor.replace("R$", "").strip()
                    preco_valor = preco_valor.replace(".", ",")
                    preco_var.set(preco_valor)
                else:
                    preco_var.set("0,00")
            except:
                preco_var.set("0,00")
        else:
            preco_var.set("0,00")

        # Validade
        ttk.Label(frame, text="Validade:", font=("Arial", 12)).grid(
            row=3, column=0, sticky=tk.W, pady=10)
        validade_entry = ttk.Entry(frame, width=35, font=("Arial", 12),
                                textvariable=validade_var)
        validade_entry.grid(row=3, column=1, pady=10, sticky=tk.EW)
        if produto:
            validade_valor = produto[3]
            if validade_valor and validade_valor != 'None' and validade_valor != '-':
                validade_var.set(validade_valor)
            else:
                validade_var.set("")

        # Código Sistema
        ttk.Label(frame, text="Código Sistema:", font=("Arial", 12)).grid(
            row=4, column=0, sticky=tk.W, pady=10)
        codigo_sistema_entry = ttk.Entry(frame, width=35, font=("Arial", 12),
                                        textvariable=codigo_sistema_var)
        codigo_sistema_entry.grid(row=4, column=1, pady=10, sticky=tk.EW)
        if produto:
            codigo_sistema_valor = produto[4]
            if codigo_sistema_valor and codigo_sistema_valor != 'None' and codigo_sistema_valor != '-':
                codigo_sistema_var.set(codigo_sistema_valor)
            else:
                codigo_sistema_var.set("")

        def salvar():
            """Salva as alterações no banco de dados"""
            codigo_barras = codigo_barras_var.get().strip()
            nome = nome_var.get().strip()
            preco_str = preco_var.get().strip()
            validade = validade_var.get().strip()
            codigo_sistema = codigo_sistema_var.get().strip()

            if not codigo_barras or not nome or not preco_str:
                messagebox.showerror(
                    "Erro", "Preencha os campos obrigatórios!")
                return

            try:
                # Converter preço para float
                preco = float(preco_str.replace(',', '.'))

                # Tratar código do sistema corretamente
                if codigo_sistema and codigo_sistema.strip():
                    try:
                        codigo_sistema = int(codigo_sistema)
                    except ValueError:
                        messagebox.showerror(
                            "Erro", "Código Sistema deve ser um número inteiro!")
                        return
                else:
                    codigo_sistema = None

                # Tratar validade (pode ser None)
                if not validade or validade.lower() == 'none' or validade == '-':
                    validade = None

                if novo:
                    # Verificar se código já existe
                    self.cursor.execute(
                        "SELECT COUNT(*) FROM produtos WHERE codigo_barras = ?", (codigo_barras,))
                    if self.cursor.fetchone()[0] > 0:
                        messagebox.showerror(
                            "Erro", "Código de barras já existe!")
                        return

                    self.cursor.execute('''
                        INSERT INTO produtos (codigo_barras, nome, preco, validade, codigo_sistema)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (codigo_barras, nome, preco, validade, codigo_sistema))
                else:
                    self.cursor.execute('''
                        UPDATE produtos
                        SET nome = ?, preco = ?, validade = ?, codigo_sistema = ?
                        WHERE codigo_barras = ?
                    ''', (nome, preco, validade, codigo_sistema, codigo_barras))

                self.conn.commit()
                self.carregar_produtos(tree)
                dialog.destroy()
                messagebox.showinfo("Sucesso", "Produto salvo com sucesso!")
            except ValueError as e:
                messagebox.showerror(
                    "Erro", f"Erro de valor: {e}\nCertifique-se de que o preço está no formato correto (ex: 5.90 ou 5,90)")
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao salvar produto: {e}")

        def cancelar():
            """Fecha a janela sem salvar"""
            dialog.destroy()

        # Frame para botões
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(20, 0), sticky=tk.EW)
        
        # Configurar pesos para os botões ficarem alinhados
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)

        # Botão Cancelar
        cancelar_btn = ttk.Button(
            button_frame,
            text="❌ Cancelar",
            command=cancelar,
            style="Danger.TButton",
            width=15
        )
        cancelar_btn.grid(row=0, column=0, padx=(0, 10), sticky=tk.EW)

        # Botão Limpar
        def limpar_campos():
            if novo:
                codigo_barras_var.set("")
                nome_var.set("")
                preco_var.set("0,00")
                validade_var.set("")
                codigo_sistema_var.set("")
                codigo_barras_entry.focus()
            else:
                # Se estiver editando, restaurar valores originais
                if produto:
                    codigo_barras_var.set(produto[0])
                    nome_var.set(produto[1])
                    try:
                        preco_valor = produto[2]
                        if preco_valor and preco_valor != 'None' and preco_valor != '-':
                            preco_valor = preco_valor.replace("R$", "").strip()
                            preco_valor = preco_valor.replace(".", ",")
                            preco_var.set(preco_valor)
                        else:
                            preco_var.set("0,00")
                    except:
                        preco_var.set("0,00")
                    
                    validade_valor = produto[3]
                    if validade_valor and validade_valor != 'None' and validade_valor != '-':
                        validade_var.set(validade_valor)
                    else:
                        validade_var.set("")
                        
                    codigo_sistema_valor = produto[4]
                    if codigo_sistema_valor and codigo_sistema_valor != 'None' and codigo_sistema_valor != '-':
                        codigo_sistema_var.set(codigo_sistema_valor)
                    else:
                        codigo_sistema_var.set("")

        limpar_btn = ttk.Button(
            button_frame,
            text="🗑️ Limpar",
            command=limpar_campos,
            style="Warning.TButton",
            width=15
        )
        limpar_btn.grid(row=0, column=1, padx=5, sticky=tk.EW)

        # Botão Salvar
        salvar_btn = ttk.Button(
            button_frame,
            text="💾 Salvar",
            command=salvar,
            style="Success.TButton",
            width=15
        )
        salvar_btn.grid(row=0, column=2, padx=(10, 0), sticky=tk.EW)

        # Adicionar atalhos
        dialog.bind('<Return>', lambda e: salvar())
        dialog.bind('<Escape>', lambda e: cancelar())
        dialog.bind('<Control-s>', lambda e: salvar())
        dialog.bind('<Control-l>', lambda e: limpar_campos())

        # Focar no campo apropriado
        if novo:
            codigo_barras_entry.focus()
        else:
            nome_entry.focus()
            nome_entry.select_range(0, tk.END)

    def excluir_produto(self, tree):
        """Exclui o produto selecionado"""
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning(
                "Atenção", "Selecione um produto para excluir!")
            return

        produto = tree.item(selected_item[0], 'values')
        if not messagebox.askyesno("Confirmar", f"Tem certeza que deseja excluir o produto '{produto[1]}'?"):
            return

        try:
            self.cursor.execute(
                "DELETE FROM produtos WHERE codigo_barras = ?", (produto[0],))
            self.conn.commit()
            self.carregar_produtos(tree)
            messagebox.showinfo("Sucesso", "Produto excluído com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao excluir produto: {e}")

    def exibir_relatorio_vendas(self):
        """Exibe o relatório de vendas em uma nova janela com filtros e gráficos"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Relatório de Vendas")
        dialog.geometry("1300x900")  # Tamanho aumentado
        dialog.transient(self.root)
        dialog.grab_set()

        # Frame principal
        frame = ttk.Frame(dialog, padding=15)  # Padding aumentado
        frame.pack(fill=tk.BOTH, expand=True)

        # Filtros
        filter_frame = ttk.LabelFrame(
            frame, text="Filtros", padding=15)  # Padding aumentado
        filter_frame.pack(fill=tk.X, pady=(0, 15))  # Espaço aumentado

        ttk.Label(filter_frame, text="Data Inicial:", font=("Arial", 12)).grid(
            row=0, column=0, padx=8, pady=8, sticky=tk.W)  # Fonte aumentada
        data_inicial_entry = ttk.Entry(
            filter_frame, width=15, font=("Arial", 12))  # Fonte aumentada
        data_inicial_entry.grid(row=0, column=1, padx=8, pady=8)
        data_inicial_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))

        ttk.Label(filter_frame, text="Data Final:", font=("Arial", 12)).grid(
            row=0, column=2, padx=8, pady=8, sticky=tk.W)  # Fonte aumentada
        data_final_entry = ttk.Entry(
            filter_frame, width=15, font=("Arial", 12))  # Fonte aumentada
        data_final_entry.grid(row=0, column=3, padx=8, pady=8)
        data_final_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))

        def aplicar_filtros():
            """Aplica os filtros de data e atualiza a tabela e gráficos"""
            data_inicial = data_inicial_entry.get().strip()
            data_final = data_final_entry.get().strip()
            self.carregar_vendas(tree, data_inicial, data_final)
            self.atualizar_estatisticas(stats_text, data_inicial, data_final)

        ttk.Button(filter_frame, text="Aplicar Filtros (ENTER)", command=aplicar_filtros,
                   style="Accent.TButton").grid(row=0, column=4, padx=15, pady=8)

        # Adicionar atalho Enter
        data_final_entry.bind('<Return>', lambda e: aplicar_filtros())

        # Tabela de vendas com fonte maior
        columns = ('id', 'data_hora', 'total', 'forma_pagamento', 'troco')
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=15)

        # Configurar colunas
        style = ttk.Style()
        style.configure("Report.Treeview", font=('Arial', 11))  # Fonte maior
        style.configure("Report.Treeview.Heading", font=(
            'Arial', 12, 'bold'))  # Fonte maior

        tree.heading('id', text='ID')
        tree.heading('data_hora', text='Data e Hora')
        tree.heading('total', text='Total (R$)')
        tree.heading('forma_pagamento', text='Forma de Pagamento')
        tree.heading('troco', text='Troco (R$)')

        tree.column('id', width=60, anchor=tk.CENTER)  # Largura aumentada
        # Largura aumentada
        tree.column('data_hora', width=180, anchor=tk.CENTER)
        tree.column('total', width=120, anchor=tk.E)  # Largura aumentada
        tree.column('forma_pagamento', width=150,
                    anchor=tk.CENTER)  # Largura aumentada
        tree.column('troco', width=120, anchor=tk.E)  # Largura aumentada

        # Scrollbar
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Detalhes da venda
        details_frame = ttk.LabelFrame(
            frame, text="Detalhes da Venda", padding=15)  # Padding aumentado
        details_frame.pack(fill=tk.BOTH, expand=True,
                           pady=(15, 0))  # Espaço aumentado

        details_text = scrolledtext.ScrolledText(
            details_frame, height=10, font=("Consolas", 11))  # Fonte aumentada
        details_text.pack(fill=tk.BOTH, expand=True)

        def exibir_detalhes(event):
            """Exibe os detalhes da venda selecionada de forma visual"""
            selected_item = tree.selection()
            if not selected_item:
                return

            venda_id = tree.item(selected_item[0], 'values')[0]
            self.cursor.execute(
                "SELECT itens, cpf FROM vendas WHERE id = ?", (venda_id,))
            venda = self.cursor.fetchone()

            if venda:
                # Converte a string de itens para uma lista de dicionários
                detalhes = eval(venda[0])
                cpf = venda[1]  # Obtém o CPF, se existir
                details_text.delete(1.0, tk.END)
                details_text.insert(
                    tk.END, f"Detalhes da Venda ID {venda_id}:\n\n")
                if cpf:
                    details_text.insert(tk.END, f"CPF: {cpf}\n\n")
                for item in detalhes:
                    details_text.insert(tk.END, f"Produto: {item['nome']}\n")
                    details_text.insert(
                        tk.END, f"  Código: {item['codigo']}\n")
                    details_text.insert(
                        tk.END, f"  Quantidade: {item['quantidade']}\n")
                    if 'peso' in item and item['peso'] > 0:
                        details_text.insert(
                            tk.END, f"  Peso: {item['peso']}g\n")
                    details_text.insert(
                        tk.END, f"  Preço Unitário: R$ {item['preco']:.2f}\n")
                    details_text.insert(
                        tk.END, f"  Total: R$ {item['total']:.2f}\n")
                    details_text.insert(tk.END, "-" * 40 + "\n")

        tree.bind("<<TreeviewSelect>>", exibir_detalhes)

        # Estatísticas do dia
        stats_frame = ttk.LabelFrame(
            frame, text="Estatísticas do Dia", padding=15)  # Padding aumentado
        stats_frame.pack(fill=tk.BOTH, expand=True,
                         pady=(15, 0))  # Espaço aumentado

        stats_text = scrolledtext.ScrolledText(
            stats_frame, height=10, font=("Consolas", 11))  # Fonte aumentada
        stats_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Carregar vendas do dia atual e atualizar estatísticas
        self.carregar_vendas(tree, datetime.now().strftime(
            "%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d"))
        self.atualizar_estatisticas(stats_text, datetime.now().strftime(
            "%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d"))

    def atualizar_estatisticas(self, stats_text_widget, data_inicial, data_final):
        """Atualiza as estatísticas com base no período"""
        try:
            # Buscar vendas agrupadas por forma de pagamento
            self.cursor.execute(
                "SELECT forma_pagamento, SUM(total) FROM vendas WHERE DATE(data_hora) BETWEEN ? AND ? GROUP BY forma_pagamento",
                (data_inicial, data_final)
            )
            pagamentos = self.cursor.fetchall()

            # Calcular total de vendas
            total_vendas = 0
            stats_text = f"📊 Resumo de Vendas ({data_inicial} a {data_final}):\n\n"
            for pagamento in pagamentos:
                stats_text += f"• {pagamento[0].capitalize()}: R$ {pagamento[1]:.2f}\n"
                total_vendas += pagamento[1]

            stats_text += f"\n💰 Total de Vendas: R$ {total_vendas:.2f}\n"

            # Buscar número total de vendas
            self.cursor.execute(
                "SELECT COUNT(*) FROM vendas WHERE DATE(data_hora) BETWEEN ? AND ?",
                (data_inicial, data_final)
            )
            total_vendas_count = self.cursor.fetchone()[0]
            stats_text += f"📈 Número de Vendas: {total_vendas_count}\n"

            # Calcular valor médio por venda
            if total_vendas_count > 0:
                valor_medio = total_vendas / total_vendas_count
                stats_text += f"📐 Valor Médio por Venda: R$ {valor_medio:.2f}\n"

            # Atualizar o widget de texto
            stats_text_widget.delete(1.0, tk.END)
            stats_text_widget.insert(tk.END, stats_text)

        except Exception as e:
            print(f"Erro ao atualizar estatísticas: {e}")

    def carregar_vendas(self, tree, data_inicial, data_final):
        """Carrega os dados da tabela de vendas no Treeview com base no período"""
        # Limpar tabela
        for item in tree.get_children():
            tree.delete(item)

        # Buscar vendas no banco de dados
        self.cursor.execute(
            "SELECT id, data_hora, total, forma_pagamento, troco FROM vendas WHERE DATE(data_hora) BETWEEN ? AND ? ORDER BY data_hora DESC",
            (data_inicial, data_final)
        )
        vendas = self.cursor.fetchall()

        # Adicionar vendas na tabela
        for venda in vendas:
            tree.insert('', 'end', values=(
                venda[0],  # ID
                venda[1],  # Data e Hora
                f"R$ {venda[2]:.2f}".replace('.', ','),  # Total
                venda[3],  # Forma de Pagamento
                f"R$ {venda[4]:.2f}".replace('.', ',')  # Troco
            ))


def verificar_dependencias():
    """Verifica e instala dependências ausentes."""
    dependencias = ['pandas', 'pillow', 'pywin32']
    for pacote in dependencias:
        try:
            __import__(pacote)
        except ImportError:
            print(f"Dependência ausente: {pacote}. Instalando...")
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', pacote])


if __name__ == "__main__":
    multiprocessing.freeze_support()
    # verificar_dependencias()
    app = PDVSystem()
    app.run()
