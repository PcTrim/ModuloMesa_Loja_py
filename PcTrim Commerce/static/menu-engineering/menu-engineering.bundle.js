const {
  useState,
  useEffect,
  useCallback
} = React;
const RechartsLib = window.Recharts || {};
const {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} = RechartsLib;

// ==================== CONFIGURATION ====================
const API_BASE = window.ME_API_BASE || '';
const HOME_URL = window.ME_HOME || '/';
const fetchOpts = {
  credentials: 'same-origin',
  headers: {
    Accept: 'application/json',
    'X-Requested-With': 'XMLHttpRequest'
  }
};
const readApiError = async response => {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json();
    detail = body.erro || body.mensagem || detail;
  } catch (_) {
    try {
      const text = (await response.text()).trim();
      if (text) detail = text.slice(0, 180);
    } catch (_) {}
  }
  return detail;
};
const fetchJson = async url => {
  const response = await fetch(url, fetchOpts);
  if (!response.ok) {
    return {
      ok: false,
      error: await readApiError(response),
      data: null
    };
  }
  try {
    return {
      ok: true,
      error: null,
      data: await response.json()
    };
  } catch (err) {
    return {
      ok: false,
      error: err.message || 'Resposta invalida da API',
      data: null
    };
  }
};

// ==================== DESIGN SYSTEM ====================
const COLORS = {
  purple: '#7c3aed',
  purpleLight: '#a78bfa',
  green: '#10b981',
  red: '#f87171',
  yellow: '#fbbf24',
  orange: '#f97316',
  blue: '#3b82f6',
  pink: '#ec4899',
  cyan: '#06b6d4'
};
const THEME = {
  dark: {
    bg: '#0f0f14',
    surface: '#1a1a28',
    surfaceHover: '#252538',
    border: '#2a2a40',
    text: '#e8e8f0',
    textMuted: '#888fa0',
    inputBg: '#10101a'
  },
  light: {
    bg: '#f1f5f9',
    surface: '#ffffff',
    surfaceHover: '#f8fafc',
    border: '#c8d0e0',
    text: '#0f172a',
    textMuted: '#64748b',
    inputBg: '#f8fafc'
  }
};

// ==================== UTILITIES ====================
const formatCurrency = value => {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL'
  }).format(value);
};
const formatPercent = value => {
  return `${(value * 100).toFixed(1)}%`;
};
const getMarginColor = margin => {
  if (margin > 0.4) return COLORS.green;
  if (margin > 0.2) return COLORS.yellow;
  return COLORS.red;
};
const getMarginLabel = margin => {
  if (margin > 0.4) return 'Excelente';
  if (margin > 0.2) return 'Boa';
  if (margin > 0) return 'Baixa';
  return 'Negativa';
};

// ==================== COMPONENTS ====================

// KPI Card Component
const KPICard = ({
  title,
  value,
  trend,
  icon,
  color
}) => {
  const isPositive = trend >= 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-card",
    style: {
      borderColor: color
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-header"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-icon",
    style: {
      color
    }
  }, icon), /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-title"
  }, title)), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-value"
  }, value), trend !== null && /*#__PURE__*/React.createElement("div", {
    className: `me-kpi-trend ${isPositive ? 'positive' : 'negative'}`
  }, isPositive ? '↑' : '↓', " ", Math.abs(trend).toFixed(1), "%"));
};

// Upload Zone Component
const UploadZone = ({
  onUpload,
  uploadedItems
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const handleDragOver = e => {
    e.preventDefault();
    setIsDragging(true);
  };
  const handleDragLeave = () => {
    setIsDragging(false);
  };
  const handleDrop = e => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };
  const handleFileSelect = e => {
    const files = e.target.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };
  const handleFileUpload = async file => {
    setIsUploading(true);
    const text = await file.text();
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/import-xml`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          xml: text
        })
      });
      const data = await response.json();
      if (data.sucesso) {
        onUpload(data);
      } else {
        alert('Erro ao importar XML: ' + data.erro);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert('Erro ao fazer upload do arquivo');
    } finally {
      setIsUploading(false);
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "me-upload-section"
  }, /*#__PURE__*/React.createElement("div", {
    className: `me-upload-zone ${isDragging ? 'dragging' : ''} ${isUploading ? 'uploading' : ''}`,
    onDragOver: handleDragOver,
    onDragLeave: handleDragLeave,
    onDrop: handleDrop
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-upload-content"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "upload-cloud",
    className: "me-upload-icon"
  }), /*#__PURE__*/React.createElement("p", {
    className: "me-upload-text"
  }, "Arraste o XML da NF-e ou clique para selecionar"), /*#__PURE__*/React.createElement("p", {
    className: "me-upload-subtext"
  }, "Suporta arquivos .xml"), /*#__PURE__*/React.createElement("input", {
    type: "file",
    accept: ".xml",
    onChange: handleFileSelect,
    className: "me-upload-input",
    disabled: isUploading
  }), !isUploading && /*#__PURE__*/React.createElement("button", {
    className: "me-upload-btn"
  }, "Selecionar Arquivo"), isUploading && /*#__PURE__*/React.createElement("div", {
    className: "me-upload-progress"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-progress-bar"
  })))), uploadedItems.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "me-upload-preview"
  }, /*#__PURE__*/React.createElement("h4", {
    className: "me-preview-title"
  }, "Itens Importados"), uploadedItems.map((item, index) => /*#__PURE__*/React.createElement("div", {
    key: index,
    className: "me-preview-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-preview-name"
  }, item.name), /*#__PURE__*/React.createElement("span", {
    className: "me-preview-cost"
  }, formatCurrency(item.cost_per_unit))))));
};

// Alert Panel Component
const AlertPanel = ({
  alerts
}) => {
  if (!alerts || alerts.length === 0) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "me-alert-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-alert-header"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "alert-triangle",
    className: "me-alert-icon"
  }), /*#__PURE__*/React.createElement("h3", {
    className: "me-alert-title"
  }, "Alertas de Pre\xE7o")), alerts.map((alert, index) => /*#__PURE__*/React.createElement("div", {
    key: index,
    className: "me-alert-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-alert-text"
  }, alert.message), /*#__PURE__*/React.createElement("span", {
    className: `me-alert-badge ${alert.type}`
  }, alert.type === 'increase' ? '↑' : '↓', " ", Math.abs(alert.value).toFixed(1), "%"))));
};

// Category Chart Component
const getCategoryColor = category => {
  const colors = {
    protein: COLORS.purple,
    dairy: COLORS.blue,
    bakery: COLORS.orange,
    vegetables: COLORS.green,
    other: COLORS.cyan
  };
  return colors[String(category || '').toLowerCase()] || COLORS.purple;
};
const CategoryChartFallback = ({
  data
}) => {
  const maxValue = Math.max(...data.map(item => Math.abs(item.percentage_change || 0)), 1);
  return /*#__PURE__*/React.createElement("div", {
    className: "me-chart-fallback",
    role: "img",
    "aria-label": "Varia\xE7\xE3o por categoria"
  }, data.map(item => {
    const value = Number(item.percentage_change) || 0;
    const height = Math.max(4, Math.abs(value) / maxValue * 100);
    const color = getCategoryColor(item.category);
    return /*#__PURE__*/React.createElement("div", {
      key: item.category,
      className: "me-chart-fallback-bar"
    }, /*#__PURE__*/React.createElement("span", {
      className: "me-chart-fallback-value"
    }, value >= 0 ? '+' : '', value.toFixed(1), "%"), /*#__PURE__*/React.createElement("div", {
      className: "me-chart-fallback-fill",
      style: {
        height: `${height}%`,
        backgroundColor: color
      },
      title: `${item.category}: ${value.toFixed(1)}%`
    }), /*#__PURE__*/React.createElement("span", {
      className: "me-chart-fallback-label"
    }, item.category));
  }));
};
const CategoryChart = ({
  data
}) => {
  if (!data || data.length === 0) {
    return /*#__PURE__*/React.createElement("div", {
      className: "me-chart-section"
    }, /*#__PURE__*/React.createElement("h3", {
      className: "me-section-title"
    }, "Varia\xE7\xE3o por Categoria"), /*#__PURE__*/React.createElement("p", {
      className: "me-chart-empty"
    }, "Sem dados ainda. Importe uma NF-e para come\xE7ar."));
  }
  const chartData = data.map(item => ({
    ...item,
    fill: getCategoryColor(item.category)
  }));
  if (!BarChart || !ResponsiveContainer) {
    return /*#__PURE__*/React.createElement("div", {
      className: "me-chart-section"
    }, /*#__PURE__*/React.createElement("h3", {
      className: "me-section-title"
    }, "Varia\xE7\xE3o por Categoria"), /*#__PURE__*/React.createElement(CategoryChartFallback, {
      data: chartData
    }));
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "me-chart-section"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "me-section-title"
  }, "Varia\xE7\xE3o por Categoria"), /*#__PURE__*/React.createElement("div", {
    className: "me-chart-container"
  }, /*#__PURE__*/React.createElement(ResponsiveContainer, {
    width: "100%",
    height: 250
  }, /*#__PURE__*/React.createElement(BarChart, {
    data: chartData
  }, /*#__PURE__*/React.createElement(XAxis, {
    dataKey: "category",
    stroke: "#888fa0",
    style: {
      fontSize: '12px'
    }
  }), /*#__PURE__*/React.createElement(YAxis, {
    stroke: "#888fa0",
    style: {
      fontSize: '12px'
    }
  }), /*#__PURE__*/React.createElement(Tooltip, {
    contentStyle: {
      backgroundColor: THEME.dark.surface,
      border: `1px solid ${THEME.dark.border}`,
      borderRadius: '8px'
    },
    itemStyle: {
      color: THEME.dark.text
    },
    formatter: value => [`${value.toFixed(1)}%`, 'Variação']
  }), /*#__PURE__*/React.createElement(Bar, {
    dataKey: "percentage_change",
    radius: [4, 4, 0, 0]
  }, chartData.map((entry, index) => /*#__PURE__*/React.createElement(Cell, {
    key: `cell-${index}`,
    fill: entry.fill
  })))))));
};

// Recipe Table Component
const RecipeTable = ({
  recipes,
  onSelectRecipe
}) => {
  const [sortField, setSortField] = useState('name');
  const [sortDirection, setSortDirection] = useState('asc');
  const [searchTerm, setSearchTerm] = useState('');
  const handleSort = field => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };
  const handleViewDetails = async recipe => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/recipe/${recipe.id}/cost`, fetchOpts);
      const data = await response.json();
      if (data.erro) {
        alert('Erro ao carregar detalhes: ' + data.erro);
      } else {
        onSelectRecipe(data);
      }
    } catch (error) {
      console.error('Error fetching recipe details:', error);
      alert('Erro ao carregar detalhes da receita');
    }
  };
  const filteredRecipes = recipes.filter(recipe => recipe.name.toLowerCase().includes(searchTerm.toLowerCase())).sort((a, b) => {
    const aValue = a[sortField];
    const bValue = b[sortField];
    if (typeof aValue === 'string') {
      return sortDirection === 'asc' ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
    }
    return sortDirection === 'asc' ? aValue - bValue : bValue - aValue;
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "me-recipes-section"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-section-header"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "me-section-title"
  }, "Receitas"), /*#__PURE__*/React.createElement("div", {
    className: "me-search-box"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "search",
    className: "me-search-icon"
  }), /*#__PURE__*/React.createElement("input", {
    type: "text",
    placeholder: "Buscar receitas...",
    value: searchTerm,
    onChange: e => setSearchTerm(e.target.value),
    className: "me-search-input"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-table-container"
  }, /*#__PURE__*/React.createElement("table", {
    className: "me-table"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    onClick: () => handleSort('name')
  }, "Nome ", sortField === 'name' && (sortDirection === 'asc' ? '↑' : '↓')), /*#__PURE__*/React.createElement("th", {
    onClick: () => handleSort('cost')
  }, "Custo ", sortField === 'cost' && (sortDirection === 'asc' ? '↑' : '↓')), /*#__PURE__*/React.createElement("th", {
    onClick: () => handleSort('price')
  }, "Pre\xE7o ", sortField === 'price' && (sortDirection === 'asc' ? '↑' : '↓')), /*#__PURE__*/React.createElement("th", {
    onClick: () => handleSort('margin')
  }, "Margem ", sortField === 'margin' && (sortDirection === 'asc' ? '↑' : '↓')), /*#__PURE__*/React.createElement("th", null, "A\xE7\xF5es"))), /*#__PURE__*/React.createElement("tbody", null, filteredRecipes.map(recipe => /*#__PURE__*/React.createElement("tr", {
    key: recipe.id,
    className: "me-table-row"
  }, /*#__PURE__*/React.createElement("td", {
    className: "me-table-name"
  }, recipe.name), /*#__PURE__*/React.createElement("td", {
    className: "me-table-cost"
  }, formatCurrency(recipe.cost)), /*#__PURE__*/React.createElement("td", {
    className: "me-table-price"
  }, formatCurrency(recipe.price)), /*#__PURE__*/React.createElement("td", {
    className: "me-table-margin"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-margin-badge",
    style: {
      backgroundColor: getMarginColor(recipe.margin) + '20',
      color: getMarginColor(recipe.margin)
    }
  }, formatPercent(recipe.margin))), /*#__PURE__*/React.createElement("td", {
    className: "me-table-actions"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn-icon",
    onClick: () => handleViewDetails(recipe),
    title: "Ver detalhes"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "eye",
    size: 16
  })))))))));
};

// Recipe Detail Modal Component
const RecipeDetailModal = ({
  recipe,
  onClose
}) => {
  if (!recipe) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "me-modal-overlay",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-modal",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-modal-header"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "me-modal-title"
  }, recipe.recipe_name), /*#__PURE__*/React.createElement("button", {
    className: "me-modal-close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-modal-summary"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-summary-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-summary-label"
  }, "Custo Total"), /*#__PURE__*/React.createElement("span", {
    className: "me-summary-value"
  }, formatCurrency(recipe.cost))), /*#__PURE__*/React.createElement("div", {
    className: "me-summary-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-summary-label"
  }, "Pre\xE7o de Venda"), /*#__PURE__*/React.createElement("span", {
    className: "me-summary-value"
  }, formatCurrency(recipe.price))), /*#__PURE__*/React.createElement("div", {
    className: "me-summary-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-summary-label"
  }, "Margem"), /*#__PURE__*/React.createElement("span", {
    className: "me-summary-value me-margin-value",
    style: {
      color: getMarginColor(recipe.margin)
    }
  }, formatPercent(recipe.margin)))), /*#__PURE__*/React.createElement("h4", {
    className: "me-modal-subtitle"
  }, "Ingredientes"), /*#__PURE__*/React.createElement("div", {
    className: "me-ingredients-list"
  }, recipe.ingredients && recipe.ingredients.map((ing, index) => /*#__PURE__*/React.createElement("div", {
    key: index,
    className: "me-ingredient-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-name"
  }, ing.name), /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-qty"
  }, ing.qty), /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-cost"
  }, formatCurrency(ing.cost)))))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onClose
  }, "Fechar"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "printer",
    size: 16,
    style: {
      marginRight: '8px'
    }
  }), "Imprimir"))));
};

// ==================== MAIN COMPONENT ====================
const MenuEngineering = () => {
  const [ingredients, setIngredients] = useState([]);
  const [recipes, setRecipes] = useState([]);
  const [variations, setVariations] = useState([]);
  const [selectedRecipe, setSelectedRecipe] = useState(null);
  const [uploadedItems, setUploadedItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiWarning, setApiWarning] = useState('');
  const [alerts, setAlerts] = useState([]);

  // Fetch data on mount
  useEffect(() => {
    fetchData();
  }, []);
  const fetchData = async () => {
    try {
      setLoading(true);
      setApiWarning('');
      const [ingredientsRes, recipesRes, variationsRes] = await Promise.all([fetchJson(`${API_BASE}/menu-engineering/ingredients`), fetchJson(`${API_BASE}/menu-engineering/recipes`), fetchJson(`${API_BASE}/menu-engineering/category-variation`)]);
      const warnings = [];
      if (!ingredientsRes.ok) warnings.push(`Ingredientes: ${ingredientsRes.error}`);
      if (!recipesRes.ok) warnings.push(`Receitas: ${recipesRes.error}`);
      if (!variationsRes.ok) warnings.push(`Variacao: ${variationsRes.error}`);
      if (warnings.length) setApiWarning(warnings.join(' | '));
      setIngredients(ingredientsRes.ok ? ingredientsRes.data.ingredients || [] : []);
      setRecipes(recipesRes.ok ? recipesRes.data.recipes || [] : []);
      const variations = variationsRes.ok ? variationsRes.data.variations || [] : [];
      setVariations(variations);
      const newAlerts = variations.filter(v => Math.abs(v.percentage_change) > 5).map(v => ({
        message: `${v.category} variou ${v.percentage_change > 0 ? '+' : ''}${v.percentage_change.toFixed(1)}%`,
        value: v.percentage_change,
        type: v.percentage_change > 0 ? 'increase' : 'decrease'
      }));
      setAlerts(newAlerts);
    } catch (error) {
      console.error('Error fetching data:', error);
      setApiWarning(error.message || 'Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  // Calculate KPIs
  const avgMargin = recipes.length > 0 ? recipes.reduce((sum, r) => sum + r.margin, 0) / recipes.length : 0;

  // Initialize Lucide icons
  useEffect(() => {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  });
  if (loading) {
    return /*#__PURE__*/React.createElement("div", {
      className: "me-loading"
    }, /*#__PURE__*/React.createElement("div", {
      className: "me-spinner"
    }), /*#__PURE__*/React.createElement("p", null, "Carregando..."));
  }
  return /*#__PURE__*/React.createElement("div", {
    className: "me-container"
  }, /*#__PURE__*/React.createElement("header", {
    className: "me-header"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-header-left"
  }, /*#__PURE__*/React.createElement("a", {
    href: HOME_URL,
    className: "me-home-btn"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "home",
    size: 18
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-brand"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "chef-hat",
    size: 24,
    style: {
      color: COLORS.purple
    }
  }), /*#__PURE__*/React.createElement("h1", null, "Custos & Margens"))), /*#__PURE__*/React.createElement("div", {
    className: "me-header-right"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-theme-toggle",
    id: "theme-toggle"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "sun",
    className: "icon-light",
    size: 18
  }), /*#__PURE__*/React.createElement("i", {
    "data-lucide": "moon",
    className: "icon-dark",
    size: 18
  })))), /*#__PURE__*/React.createElement("main", {
    className: "me-main"
  }, apiWarning && /*#__PURE__*/React.createElement("div", {
    className: "me-api-warning",
    role: "alert"
  }, apiWarning, ' ', /*#__PURE__*/React.createElement("a", {
    href: `${HOME_URL}`
  }, "Voltar ao painel")), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-grid"
  }, /*#__PURE__*/React.createElement(KPICard, {
    title: "Ingredientes",
    value: ingredients.length,
    trend: null,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "package",
      size: 24
    }),
    color: COLORS.purple
  }), /*#__PURE__*/React.createElement(KPICard, {
    title: "Receitas",
    value: recipes.length,
    trend: null,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "book-open",
      size: 24
    }),
    color: COLORS.blue
  }), /*#__PURE__*/React.createElement(KPICard, {
    title: "Margem M\xE9dia",
    value: formatPercent(avgMargin),
    trend: avgMargin * 100,
    icon: /*#__PURE__*/React.createElement("i", {
      "data-lucide": "trending-up",
      size: 24
    }),
    color: avgMargin > 0.2 ? COLORS.green : COLORS.red
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-top-grid"
  }, /*#__PURE__*/React.createElement(UploadZone, {
    onUpload: data => {
      setUploadedItems(data.imported_items || []);
      fetchData();
    },
    uploadedItems: uploadedItems
  }), /*#__PURE__*/React.createElement(AlertPanel, {
    alerts: alerts
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-charts-grid"
  }, /*#__PURE__*/React.createElement(CategoryChart, {
    data: variations
  })), /*#__PURE__*/React.createElement(RecipeTable, {
    recipes: recipes,
    onSelectRecipe: setSelectedRecipe
  })), selectedRecipe && /*#__PURE__*/React.createElement(RecipeDetailModal, {
    recipe: selectedRecipe,
    onClose: () => setSelectedRecipe(null)
  }));
};

// Render
const rootEl = document.getElementById('root');
if (!window.React || !window.ReactDOM) {
  if (rootEl) {
    rootEl.innerHTML = '<div class="me-loading"><p>Não foi possível carregar a interface. Recarregue a página (Ctrl+F5).</p><p><a href="' + HOME_URL + '">Voltar ao painel</a></p></div>';
  }
} else {
  const root = ReactDOM.createRoot(rootEl);
  root.render(/*#__PURE__*/React.createElement(MenuEngineering, null));
}