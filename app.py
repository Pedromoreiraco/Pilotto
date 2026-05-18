import os
import io
import tempfile
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from parsers.pdf_parser import parse_pdf
from parsers.excel_parser import parse_excel
from parsers.normalizer import normalize_transactions
from categorizer.rules import categorize, get_all_categories
from categorizer.ai_categorizer import categorize_batch

load_dotenv()

st.set_page_config(
    page_title="Pilotto",
    page_icon="🛩️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        border-left: 4px solid #dee2e6;
    }
    .metric-positive { border-left-color: #28a745; }
    .metric-negative { border-left-color: #dc3545; }
    .metric-neutral  { border-left-color: #6c757d; }
    .value-positive { color: #28a745; font-weight: 600; }
    .value-negative { color: #dc3545; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Session state initialisation ────────────────────────────────────────────

def _init_state():
    defaults = {
        "transactions_df": pd.DataFrame(),
        "uploaded_files_names": [],
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "categorization_done": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Configurações")
    st.divider()

    api_key_input = st.text_input(
        "Chave API Anthropic (opcional)",
        value=st.session_state.api_key,
        type="password",
        help="Usada para categorização com IA. Se vazia, apenas regras locais são aplicadas.",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input

    if st.session_state.api_key:
        st.success("✅ API key configurada")
    else:
        st.info("ℹ️ Sem API key — usando apenas regras locais")

    st.divider()

    if st.session_state.uploaded_files_names:
        st.subheader("📂 Arquivos carregados")
        for name in st.session_state.uploaded_files_names:
            st.text(f"• {name}")

        if st.button("🗑️ Limpar todos os dados", use_container_width=True):
            st.session_state.transactions_df = pd.DataFrame()
            st.session_state.uploaded_files_names = []
            st.session_state.categorization_done = False
            st.rerun()
    else:
        st.caption("Nenhum arquivo carregado ainda.")

    st.divider()
    st.caption("Pilotto v1.0 — Seu dinheiro no pilotto automático")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _process_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name
    suffix = name.rsplit(".", 1)[-1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        if suffix == "pdf":
            raw = parse_pdf(tmp_path)
        elif suffix in ("xlsx", "xls", "csv"):
            raw = parse_excel(tmp_path)
        else:
            raise ValueError(f"Formato não suportado: .{suffix}")
    finally:
        os.unlink(tmp_path)

    return normalize_transactions(raw, source_name=name)


def _apply_categorization(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    categories = get_all_categories()
    result_cats = []

    for _, row in df.iterrows():
        cat = categorize(row["description"])
        result_cats.append(cat if cat else "__UNCATEGORIZED__")

    uncategorized_idx = [i for i, c in enumerate(result_cats) if c == "__UNCATEGORIZED__"]

    if uncategorized_idx and st.session_state.api_key:
        uncategorized_txns = [
            df.iloc[i].to_dict() for i in uncategorized_idx
        ]
        with st.spinner(f"Categorizando {len(uncategorized_txns)} transações com IA..."):
            ai_cats = categorize_batch(
                uncategorized_txns, categories, api_key=st.session_state.api_key
            )
        for list_pos, df_idx in enumerate(uncategorized_idx):
            result_cats[df_idx] = ai_cats[list_pos]
    else:
        for i in uncategorized_idx:
            result_cats[i] = "Outros"

    df = df.copy()
    df["categoria"] = result_cats
    return df


def _format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _color_value(value: float) -> str:
    formatted = _format_currency(value)
    cls = "value-positive" if value >= 0 else "value-negative"
    return f'<span class="{cls}">{formatted}</span>'


# ── Tab: Upload ───────────────────────────────────────────────────────────────

def render_upload_tab():
    st.header("📤 Upload de Extratos")
    st.markdown(
        "Faça o upload dos seus extratos bancários ou faturas de cartão de crédito. "
        "Formatos aceitos: **PDF**, **Excel (.xlsx)** e **CSV**."
    )

    uploaded_files = st.file_uploader(
        "Arraste os arquivos ou clique para selecionar",
        type=["pdf", "xlsx", "xls", "csv"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploaded_files:
        new_files = [
            f for f in uploaded_files
            if f.name not in st.session_state.uploaded_files_names
        ]

        if new_files:
            progress_bar = st.progress(0, text="Processando arquivos...")
            new_dfs = []
            errors = []

            for idx, uploaded_file in enumerate(new_files):
                progress_bar.progress(
                    (idx + 1) / len(new_files),
                    text=f"Processando {uploaded_file.name}...",
                )
                try:
                    df = _process_file(uploaded_file)
                    new_dfs.append(df)
                    st.session_state.uploaded_files_names.append(uploaded_file.name)
                except Exception as e:
                    errors.append((uploaded_file.name, str(e)))

            progress_bar.empty()

            for name, err in errors:
                st.error(f"**{name}**: {err}")

            if new_dfs:
                combined = pd.concat(new_dfs, ignore_index=True)

                if not st.session_state.transactions_df.empty:
                    combined = pd.concat(
                        [st.session_state.transactions_df, combined],
                        ignore_index=True,
                    )
                    combined = combined.drop_duplicates(
                        subset=["date", "description", "value"]
                    ).reset_index(drop=True)

                with st.spinner("Aplicando categorização..."):
                    if "categoria" not in combined.columns:
                        combined["categoria"] = None

                    needs_cat = combined["categoria"].isna() | (combined["categoria"] == "")
                    if needs_cat.any():
                        sub = combined[needs_cat].copy()
                        sub_cat = _apply_categorization(sub)
                        combined.loc[needs_cat, "categoria"] = sub_cat["categoria"].values

                st.session_state.transactions_df = combined
                st.session_state.categorization_done = True
                st.success(
                    f"✅ {len(new_dfs)} arquivo(s) processado(s) com sucesso! "
                    f"{len(combined)} transações no total."
                )
                st.rerun()

    df = st.session_state.transactions_df
    if not df.empty:
        st.divider()
        st.subheader(f"Prévia das Transações ({len(df)} registros)")

        preview_df = df.copy()
        preview_df["data"] = preview_df["date"].dt.strftime("%d/%m/%Y")
        preview_df["valor"] = preview_df["value"].apply(_format_currency)
        preview_df["tipo"] = preview_df["type"].map({"debit": "Débito", "credit": "Crédito"})
        preview_df["arquivo"] = preview_df["source"]
        preview_df["categoria"] = preview_df["categoria"]

        st.dataframe(
            preview_df[["data", "description", "valor", "tipo", "categoria", "arquivo"]].rename(
                columns={"description": "descrição"}
            ),
            use_container_width=True,
            hide_index=True,
            height=400,
        )
    else:
        st.info("Nenhum dado carregado ainda. Faça o upload de um extrato para começar.")


# ── Tab: Dashboard ────────────────────────────────────────────────────────────

def render_dashboard_tab():
    st.header("📊 Dashboard")

    df = st.session_state.transactions_df
    if df.empty:
        st.info("Carregue extratos na aba **Upload** para ver o dashboard.")
        return

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")

    months = sorted(df["month"].unique())
    month_options = ["Todos os meses"] + [str(m) for m in months]

    selected_month_str = st.selectbox(
        "Período",
        options=month_options,
        index=0,
    )

    if selected_month_str != "Todos os meses":
        selected_period = pd.Period(selected_month_str, freq="M")
        filtered = df[df["month"] == selected_period]
    else:
        filtered = df

    receitas = filtered[filtered["value"] > 0]["value"].sum()
    despesas = filtered[filtered["value"] < 0]["value"].sum()
    saldo = receitas + despesas

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="💚 Total Receitas",
            value=_format_currency(receitas),
        )
    with col2:
        st.metric(
            label="🔴 Total Despesas",
            value=_format_currency(abs(despesas)),
        )
    with col3:
        delta_color = "normal" if saldo >= 0 else "inverse"
        st.metric(
            label="🛩️ Saldo do Mês",
            value=_format_currency(saldo),
            delta=f"{'positivo' if saldo >= 0 else 'negativo'}",
            delta_color=delta_color,
        )

    st.divider()

    expenses_df = filtered[filtered["value"] < 0].copy()
    expenses_df["abs_value"] = expenses_df["value"].abs()

    if expenses_df.empty:
        st.info("Nenhuma despesa no período selecionado.")
    else:
        cat_summary = (
            expenses_df.groupby("categoria")["abs_value"]
            .sum()
            .reset_index()
            .sort_values("abs_value", ascending=False)
        )

        col_pie, col_bar = st.columns(2)

        with col_pie:
            st.subheader("Despesas por Categoria")
            fig_pie = px.pie(
                cat_summary,
                names="categoria",
                values="abs_value",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
            )
            fig_pie.update_layout(
                showlegend=True,
                legend=dict(orientation="v", yanchor="middle", y=0.5),
                margin=dict(t=10, b=10, l=10, r=10),
                height=380,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_bar:
            st.subheader("Valor por Categoria")
            fig_bar = px.bar(
                cat_summary.sort_values("abs_value"),
                x="abs_value",
                y="categoria",
                orientation="h",
                color="abs_value",
                color_continuous_scale="Reds",
                labels={"abs_value": "Valor (R$)", "categoria": "Categoria"},
            )
            fig_bar.update_traces(
                hovertemplate="<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>"
            )
            fig_bar.update_layout(
                showlegend=False,
                coloraxis_showscale=False,
                margin=dict(t=10, b=10, l=10, r=10),
                height=380,
                xaxis_title="Valor (R$)",
                yaxis_title="",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    if len(months) > 1:
        st.divider()
        st.subheader("Evolução Mensal")

        monthly = (
            df.groupby(["month", df["value"].apply(lambda v: "Receita" if v > 0 else "Despesa")])
            ["value"]
            .sum()
            .abs()
            .reset_index()
        )
        monthly.columns = ["month", "tipo", "valor"]
        monthly["month_str"] = monthly["month"].astype(str)

        fig_trend = px.bar(
            monthly,
            x="month_str",
            y="valor",
            color="tipo",
            barmode="group",
            color_discrete_map={"Receita": "#28a745", "Despesa": "#dc3545"},
            labels={"month_str": "Mês", "valor": "Valor (R$)", "tipo": "Tipo"},
        )
        fig_trend.update_traces(
            hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>"
        )
        fig_trend.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=30, b=10, l=10, r=10),
            height=350,
        )
        st.plotly_chart(fig_trend, use_container_width=True)


# ── Tab: Transações ───────────────────────────────────────────────────────────

def render_transactions_tab():
    st.header("📋 Transações")

    df = st.session_state.transactions_df
    if df.empty:
        st.info("Carregue extratos na aba **Upload** para ver as transações.")
        return

    categories = get_all_categories()
    df = df.copy()

    st.subheader("Filtros")
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        all_cats = ["Todas"] + sorted(df["categoria"].dropna().unique().tolist())
        selected_cat = st.selectbox("Categoria", options=all_cats)

    with filter_col2:
        type_options = {"Todos": None, "Débitos (despesas)": "debit", "Créditos (receitas)": "credit"}
        selected_type_label = st.selectbox("Tipo", options=list(type_options.keys()))
        selected_type = type_options[selected_type_label]

    with filter_col3:
        min_date = df["date"].min().date()
        max_date = df["date"].max().date()
        date_range = st.date_input(
            "Período",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    filtered = df.copy()

    if selected_cat != "Todas":
        filtered = filtered[filtered["categoria"] == selected_cat]

    if selected_type:
        filtered = filtered[filtered["type"] == selected_type]

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
        filtered = filtered[
            (filtered["date"].dt.date >= start_date) &
            (filtered["date"].dt.date <= end_date)
        ]

    filtered = filtered.sort_values("date", ascending=False).reset_index(drop=True)

    st.caption(f"{len(filtered)} transação(ões) encontrada(s)")

    display_df = filtered.copy()
    display_df["Data"] = display_df["date"].dt.strftime("%d/%m/%Y")
    display_df["Descrição"] = display_df["description"]
    display_df["Valor"] = display_df["value"].apply(_format_currency)
    display_df["Tipo"] = display_df["type"].map({"debit": "Débito", "credit": "Crédito"})
    display_df["Arquivo"] = display_df["source"]
    display_df["Categoria"] = display_df["categoria"]

    edited = st.data_editor(
        display_df[["Data", "Descrição", "Valor", "Tipo", "Categoria", "Arquivo"]],
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "Data": st.column_config.TextColumn("Data", width="small"),
            "Descrição": st.column_config.TextColumn("Descrição", width="large"),
            "Valor": st.column_config.TextColumn("Valor", width="small"),
            "Tipo": st.column_config.TextColumn("Tipo", width="small"),
            "Categoria": st.column_config.SelectboxColumn(
                "Categoria",
                options=categories,
                width="medium",
            ),
            "Arquivo": st.column_config.TextColumn("Arquivo", width="medium"),
        },
    )

    if st.button("💾 Salvar alterações de categoria"):
        for i, row in edited.iterrows():
            original_idx = filtered.index[i]
            st.session_state.transactions_df.at[original_idx, "categoria"] = row["Categoria"]
        st.success("Categorias atualizadas!")
        st.rerun()

    st.divider()

    if st.button("📥 Exportar para Excel", use_container_width=False):
        export_df = filtered.copy()
        export_df["data"] = export_df["date"].dt.strftime("%d/%m/%Y")
        export_df = export_df.rename(columns={
            "description": "descrição",
            "value": "valor",
            "type": "tipo",
            "source": "arquivo",
            "categoria": "categoria",
        })
        export_df["tipo"] = export_df["tipo"].map({"debit": "Débito", "credit": "Crédito"})
        export_df = export_df[["data", "descrição", "valor", "tipo", "categoria", "arquivo"]]

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Transações")

            workbook = writer.book
            worksheet = writer.sheets["Transações"]

            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.utils import get_column_letter

            header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)

            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")

            col_widths = {"data": 14, "descrição": 50, "valor": 16, "tipo": 12, "categoria": 18, "arquivo": 30}
            for col_idx, col_name in enumerate(export_df.columns, 1):
                width = col_widths.get(col_name, 20)
                worksheet.column_dimensions[get_column_letter(col_idx)].width = width

            from openpyxl.styles import numbers as xl_numbers
            value_col_idx = list(export_df.columns).index("valor") + 1
            for row in worksheet.iter_rows(min_row=2, min_col=value_col_idx, max_col=value_col_idx):
                for cell in row:
                    cell.number_format = '#,##0.00'

        buffer.seek(0)
        st.download_button(
            label="⬇️ Baixar arquivo Excel",
            data=buffer,
            file_name="transacoes_financeiras.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ── Main layout ───────────────────────────────────────────────────────────────

st.title("🛩️ Pilotto")
st.markdown(
    "Analise seus extratos bancários e faturas de cartão de crédito de forma simples e inteligente."
)

tab_upload, tab_dashboard, tab_transactions = st.tabs(
    ["📤 Upload", "📊 Dashboard", "📋 Transações"]
)

with tab_upload:
    render_upload_tab()

with tab_dashboard:
    render_dashboard_tab()

with tab_transactions:
    render_transactions_tab()
