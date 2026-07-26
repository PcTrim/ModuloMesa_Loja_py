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
const getCategoryName = category => {
  const names = {
    protein: 'Proteína',
    dairy: 'Laticínios',
    bakery: 'Padaria',
    vegetables: 'Vegetais',
    fruits: 'Frutas',
    spices: 'Temperos',
    other: 'Outros'
  };
  return names[String(category || '').toLowerCase()] || category;
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
    const categoryName = getCategoryName(item.category);
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
      title: `${categoryName}: ${value.toFixed(1)}%`
    }), /*#__PURE__*/React.createElement("span", {
      className: "me-chart-fallback-label"
    }, categoryName));
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
  onSelectRecipe,
  onCreateRecipe
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
    className: "me-section-actions"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary",
    onClick: onCreateRecipe
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 16,
    style: {
      marginRight: '8px'
    }
  }), "Nova Receita"), /*#__PURE__*/React.createElement("div", {
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
  })))), /*#__PURE__*/React.createElement("div", {
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
  }, "Margem ", sortField === 'margin' && (sortDirection === 'asc' ? '↑' : '↓')), /*#__PURE__*/React.createElement("th", null, "A\xE7\xF5es"))), /*#__PURE__*/React.createElement("tbody", null, filteredRecipes.length === 0 ? /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    colSpan: "5",
    className: "me-table-empty"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-empty-table"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "book-open",
    size: 48,
    style: {
      color: COLORS.cyan
    }
  }), /*#__PURE__*/React.createElement("p", null, "Nenhuma receita encontrada"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onCreateRecipe
  }, "Criar primeira receita")))) : filteredRecipes.map(recipe => /*#__PURE__*/React.createElement("tr", {
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

// Create Ingredient Modal Component
const CreateIngredientModal = ({
  isOpen,
  onClose,
  onSave
}) => {
  const [name, setName] = useState('');
  const [unitType, setUnitType] = useState('g');
  const [cost, setCost] = useState('');
  const [category, setCategory] = useState('other');
  const [isSaving, setIsSaving] = useState(false);
  const handleSave = async () => {
    if (!name.trim()) {
      alert('Por favor, insira um nome para o ingrediente');
      return;
    }
    if (!cost || parseFloat(cost) <= 0) {
      alert('Por favor, insira um custo válido maior que zero');
      return;
    }
    setIsSaving(true);
    try {
      const newIngredient = {
        name: name.trim(),
        unit_type: unitType,
        current_cost_per_unit: parseFloat(cost),
        category: category
      };
      await onSave(newIngredient);
      onClose();
      setName('');
      setUnitType('g');
      setCost('');
      setCategory('other');
    } catch (error) {
      console.error('Error saving ingredient:', error);
      alert('Erro ao salvar ingrediente');
    } finally {
      setIsSaving(false);
    }
  };
  if (!isOpen) return null;
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
  }, "Novo Ingrediente"), /*#__PURE__*/React.createElement("button", {
    className: "me-modal-close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Nome do Ingrediente *"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "me-form-input",
    value: name,
    onChange: e => setName(e.target.value),
    placeholder: "Ex: carne mo\xEDda"
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-form-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Unidade de Medida"), /*#__PURE__*/React.createElement("select", {
    className: "me-form-select",
    value: unitType,
    onChange: e => setUnitType(e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "g"
  }, "Gramas (g)"), /*#__PURE__*/React.createElement("option", {
    value: "kg"
  }, "Quilogramas (kg)"), /*#__PURE__*/React.createElement("option", {
    value: "ml"
  }, "Mililitros (ml)"), /*#__PURE__*/React.createElement("option", {
    value: "l"
  }, "Litros (l)"), /*#__PURE__*/React.createElement("option", {
    value: "unit"
  }, "Unidade (unit)"))), /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Categoria"), /*#__PURE__*/React.createElement("select", {
    className: "me-form-select",
    value: category,
    onChange: e => setCategory(e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "protein"
  }, "Prote\xEDna"), /*#__PURE__*/React.createElement("option", {
    value: "dairy"
  }, "Latic\xEDnios"), /*#__PURE__*/React.createElement("option", {
    value: "bakery"
  }, "Padaria"), /*#__PURE__*/React.createElement("option", {
    value: "vegetables"
  }, "Vegetais"), /*#__PURE__*/React.createElement("option", {
    value: "fruits"
  }, "Frutas"), /*#__PURE__*/React.createElement("option", {
    value: "spices"
  }, "Temperos"), /*#__PURE__*/React.createElement("option", {
    value: "other"
  }, "Outro")))), /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Custo por Unidade (R$) *"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    step: "0.0001",
    min: "0",
    className: "me-form-input",
    value: cost,
    onChange: e => setCost(e.target.value),
    placeholder: "Ex: 0.2500"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onClose
  }, "Cancelar"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary",
    onClick: handleSave,
    disabled: isSaving
  }, isSaving ? 'Salvando...' : 'Salvar Ingrediente'))));
};

// Edit Ingredient Modal Component
const EditIngredientModal = ({
  isOpen,
  onClose,
  ingredient,
  onSave,
  categories,
  onManageCategories
}) => {
  const [name, setName] = useState('');
  const [unitType, setUnitType] = useState('g');
  const [cost, setCost] = useState('');
  const [category, setCategory] = useState('other');
  const [isSaving, setIsSaving] = useState(false);
  useEffect(() => {
    if (ingredient) {
      setName(ingredient.name || '');
      setUnitType(ingredient.unit_type || 'g');
      setCost(ingredient.current_cost_per_unit || '');
      setCategory(ingredient.category || 'other');
    }
  }, [ingredient]);
  const handleSave = async () => {
    if (!name.trim()) {
      alert('Por favor, insira um nome para o ingrediente');
      return;
    }
    if (!cost || parseFloat(cost) <= 0) {
      alert('Por favor, insira um custo válido maior que zero');
      return;
    }
    setIsSaving(true);
    try {
      const updatedIngredient = {
        id: ingredient.id,
        name: name.trim(),
        unit_type: unitType,
        current_cost_per_unit: parseFloat(cost),
        category: category
      };
      await onSave(updatedIngredient);
      onClose();
    } catch (error) {
      console.error('Error saving ingredient:', error);
      alert('Erro ao salvar ingrediente');
    } finally {
      setIsSaving(false);
    }
  };
  if (!isOpen) return null;
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
  }, "Editar Ingrediente"), /*#__PURE__*/React.createElement("button", {
    className: "me-modal-close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Nome do Ingrediente *"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "me-form-input",
    value: name,
    onChange: e => setName(e.target.value),
    placeholder: "Ex: carne mo\xEDda"
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-form-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Unidade de Medida"), /*#__PURE__*/React.createElement("select", {
    className: "me-form-select",
    value: unitType,
    onChange: e => setUnitType(e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "g"
  }, "Gramas (g)"), /*#__PURE__*/React.createElement("option", {
    value: "kg"
  }, "Quilogramas (kg)"), /*#__PURE__*/React.createElement("option", {
    value: "ml"
  }, "Mililitros (ml)"), /*#__PURE__*/React.createElement("option", {
    value: "l"
  }, "Litros (l)"), /*#__PURE__*/React.createElement("option", {
    value: "unit"
  }, "Unidade (unit)"))), /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Categoria"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: '4px'
    }
  }, /*#__PURE__*/React.createElement("select", {
    className: "me-form-select",
    value: category,
    onChange: e => setCategory(e.target.value),
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: "protein"
  }, "Prote\xEDna"), /*#__PURE__*/React.createElement("option", {
    value: "dairy"
  }, "Latic\xEDnios"), /*#__PURE__*/React.createElement("option", {
    value: "bakery"
  }, "Padaria"), /*#__PURE__*/React.createElement("option", {
    value: "vegetables"
  }, "Vegetais"), /*#__PURE__*/React.createElement("option", {
    value: "fruits"
  }, "Frutas"), /*#__PURE__*/React.createElement("option", {
    value: "spices"
  }, "Temperos"), /*#__PURE__*/React.createElement("option", {
    value: "other"
  }, "Outro"), categories.map(cat => /*#__PURE__*/React.createElement("option", {
    key: cat.id,
    value: cat.slug
  }, cat.name))), /*#__PURE__*/React.createElement("button", {
    className: "me-btn-icon",
    onClick: onManageCategories,
    title: "Gerenciar categorias"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "settings",
    size: 16
  }))))), /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Custo por Unidade (R$) *"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    step: "0.0001",
    min: "0",
    className: "me-form-input",
    value: cost,
    onChange: e => setCost(e.target.value),
    placeholder: "Ex: 0.2500"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onClose
  }, "Cancelar"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary",
    onClick: handleSave,
    disabled: isSaving
  }, isSaving ? 'Salvando...' : 'Salvar Alterações'))));
};

// Category Management Modal Component
const CategoryModal = ({
  isOpen,
  onClose,
  categories,
  onSave
}) => {
  const [newCategory, setNewCategory] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const handleAddCategory = async () => {
    if (!newCategory.trim()) {
      alert('Por favor, insira um nome para a categoria');
      return;
    }
    setIsSaving(true);
    try {
      const slug = newCategory.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]/g, '_');
      await onSave({
        name: newCategory.trim(),
        slug: slug
      });
      setNewCategory('');
    } catch (error) {
      console.error('Error adding category:', error);
      alert('Erro ao adicionar categoria');
    } finally {
      setIsSaving(false);
    }
  };
  if (!isOpen) return null;
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
  }, "Gerenciar Categorias"), /*#__PURE__*/React.createElement("button", {
    className: "me-modal-close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Nova Categoria"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: '8px'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "me-form-input",
    value: newCategory,
    onChange: e => setNewCategory(e.target.value),
    placeholder: "Ex: Bebidas",
    onKeyPress: e => e.key === 'Enter' && handleAddCategory()
  }), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary",
    onClick: handleAddCategory,
    disabled: isSaving
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 16
  })))), /*#__PURE__*/React.createElement("div", {
    className: "me-categories-list"
  }, /*#__PURE__*/React.createElement("h4", {
    className: "me-modal-subtitle"
  }, "Categorias Padr\xE3o"), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Prote\xEDna"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Latic\xEDnios"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Padaria"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Vegetais"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Frutas"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Temperos"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), /*#__PURE__*/React.createElement("div", {
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, "Outro"), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge"
  }, "Padr\xE3o")), categories.length > 0 && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("h4", {
    className: "me-modal-subtitle",
    style: {
      marginTop: '16px'
    }
  }, "Categorias Personalizadas"), categories.map(cat => /*#__PURE__*/React.createElement("div", {
    key: cat.id,
    className: "me-category-item"
  }, /*#__PURE__*/React.createElement("span", null, cat.name), /*#__PURE__*/React.createElement("span", {
    className: "me-category-badge me-category-badge-custom"
  }, "Personalizada")))))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onClose
  }, "Fechar"))));
};

// Create Recipe Modal Component
const CreateRecipeModal = ({
  isOpen,
  onClose,
  ingredients,
  onSave
}) => {
  const [recipeName, setRecipeName] = useState('');
  const [productId, setProductId] = useState('');
  const [sellingPrice, setSellingPrice] = useState('');
  const [selectedIngredients, setSelectedIngredients] = useState([]);
  const [isSaving, setIsSaving] = useState(false);
  const addIngredient = () => {
    setSelectedIngredients([...selectedIngredients, {
      ingredient_id: '',
      quantity: ''
    }]);
  };
  const removeIngredient = index => {
    setSelectedIngredients(selectedIngredients.filter((_, i) => i !== index));
  };
  const updateIngredient = (index, field, value) => {
    const updated = [...selectedIngredients];
    updated[index][field] = value;
    setSelectedIngredients(updated);
  };
  const calculateTotalCost = () => {
    return selectedIngredients.reduce((total, ing) => {
      const ingredient = ingredients.find(i => i.id === parseInt(ing.ingredient_id));
      if (ingredient && ing.quantity) {
        return total + ingredient.current_cost_per_unit * parseFloat(ing.quantity);
      }
      return total;
    }, 0);
  };
  const handleSave = async () => {
    if (!recipeName.trim()) {
      alert('Por favor, insira um nome para a receita');
      return;
    }
    if (selectedIngredients.length === 0) {
      alert('Adicione pelo menos um ingrediente');
      return;
    }
    const invalidQty = selectedIngredients.some(ing => !ing.quantity || parseFloat(ing.quantity) <= 0);
    if (invalidQty) {
      alert('Todos os ingredientes devem ter uma quantidade válida maior que zero');
      return;
    }
    const missingIngredient = selectedIngredients.some(ing => !ing.ingredient_id);
    if (missingIngredient) {
      alert('Selecione um ingrediente para cada item');
      return;
    }
    setIsSaving(true);
    try {
      const totalCost = calculateTotalCost();
      const price = parseFloat(sellingPrice) || totalCost * 1.3;
      const margin = price > 0 ? (price - totalCost) / price : 0;
      const newRecipe = {
        name: recipeName,
        product_id: parseInt(productId) || null,
        price: price,
        cost: totalCost,
        margin: margin,
        ingredients: selectedIngredients.map(ing => {
          const ingredient = ingredients.find(i => i.id === parseInt(ing.ingredient_id));
          return {
            ingredient_id: parseInt(ing.ingredient_id),
            quantity: parseFloat(ing.quantity),
            name: ingredient ? ingredient.name : '',
            unit_type: ingredient ? ingredient.unit_type : '',
            cost: ingredient ? ingredient.current_cost_per_unit * parseFloat(ing.quantity) : 0
          };
        })
      };
      await onSave(newRecipe);
      onClose();
      setRecipeName('');
      setProductId('');
      setSellingPrice('');
      setSelectedIngredients([]);
    } catch (error) {
      console.error('Error saving recipe:', error);
      alert('Erro ao salvar receita');
    } finally {
      setIsSaving(false);
    }
  };
  if (!isOpen) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "me-modal-overlay",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-modal me-modal-large",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-modal-header"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "me-modal-title"
  }, "Nova Receita"), /*#__PURE__*/React.createElement("button", {
    className: "me-modal-close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Nome da Receita *"), /*#__PURE__*/React.createElement("input", {
    type: "text",
    className: "me-form-input",
    value: recipeName,
    onChange: e => setRecipeName(e.target.value),
    placeholder: "Ex: Burger Classic"
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-form-row"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "ID do Produto (opcional)"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    className: "me-form-input",
    value: productId,
    onChange: e => setProductId(e.target.value),
    placeholder: "ID do produto no sistema"
  })), /*#__PURE__*/React.createElement("div", {
    className: "me-form-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "me-form-label"
  }, "Pre\xE7o de Venda (R$)"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    step: "0.01",
    className: "me-form-input",
    value: sellingPrice,
    onChange: e => setSellingPrice(e.target.value),
    placeholder: "Auto-calculado se vazio"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "me-ingredients-section"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-section-header"
  }, /*#__PURE__*/React.createElement("h4", {
    className: "me-modal-subtitle"
  }, "Ingredientes"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-sm me-btn-secondary",
    onClick: addIngredient
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 16,
    style: {
      marginRight: '4px'
    }
  }), "Adicionar")), selectedIngredients.length === 0 ? /*#__PURE__*/React.createElement("p", {
    className: "me-empty-state"
  }, "Nenhum ingrediente adicionado. Clique em \"Adicionar\" para come\xE7ar.") : /*#__PURE__*/React.createElement("div", {
    className: "me-recipe-ingredients-list"
  }, selectedIngredients.map((ing, index) => /*#__PURE__*/React.createElement("div", {
    key: index,
    className: "me-recipe-ingredient-row"
  }, /*#__PURE__*/React.createElement("select", {
    className: "me-form-select",
    value: ing.ingredient_id,
    onChange: e => updateIngredient(index, 'ingredient_id', e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "Selecione um ingrediente"), ingredients.map(ingredient => /*#__PURE__*/React.createElement("option", {
    key: ingredient.id,
    value: ingredient.id
  }, ingredient.name, " (", formatCurrency(ingredient.current_cost_per_unit), "/", ingredient.unit_type, ")"))), /*#__PURE__*/React.createElement("input", {
    type: "number",
    step: "0.01",
    className: "me-form-input me-form-input-sm",
    placeholder: "Qtd",
    value: ing.quantity,
    onChange: e => updateIngredient(index, 'quantity', e.target.value)
  }), /*#__PURE__*/React.createElement("button", {
    className: "me-btn-icon me-btn-icon-danger",
    onClick: () => removeIngredient(index),
    title: "Remover"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "trash-2",
    size: 16
  })))))), selectedIngredients.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "me-cost-preview"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-cost-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-cost-label"
  }, "Custo Total Estimado:"), /*#__PURE__*/React.createElement("span", {
    className: "me-cost-value"
  }, formatCurrency(calculateTotalCost()))), sellingPrice && /*#__PURE__*/React.createElement("div", {
    className: "me-cost-item"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-cost-label"
  }, "Margem Estimada:"), /*#__PURE__*/React.createElement("span", {
    className: "me-cost-value",
    style: {
      color: getMarginColor((parseFloat(sellingPrice) - calculateTotalCost()) / parseFloat(sellingPrice))
    }
  }, formatPercent((parseFloat(sellingPrice) - calculateTotalCost()) / parseFloat(sellingPrice)))))), /*#__PURE__*/React.createElement("div", {
    className: "me-modal-footer"
  }, /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-secondary",
    onClick: onClose
  }, "Cancelar"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-primary",
    onClick: handleSave,
    disabled: isSaving
  }, isSaving ? 'Salvando...' : 'Salvar Receita'))));
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
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isIngredientModalOpen, setIsIngredientModalOpen] = useState(false);
  const [isEditIngredientModalOpen, setIsEditIngredientModalOpen] = useState(false);
  const [selectedIngredient, setSelectedIngredient] = useState(null);
  const [isCategoryModalOpen, setIsCategoryModalOpen] = useState(false);
  const [categories, setCategories] = useState([]);
  const [useMockData, setUseMockData] = useState(false);

  // Mock data for client_id 2003
  const mockIngredients = [{
    id: 19,
    name: 'carne moída',
    unit_type: 'g',
    current_cost_per_unit: 0.2500,
    category: 'protein'
  }, {
    id: 20,
    name: 'queijo',
    unit_type: 'g',
    current_cost_per_unit: 0.6667,
    category: 'dairy'
  }, {
    id: 21,
    name: 'pão',
    unit_type: 'unit',
    current_cost_per_unit: 1.5000,
    category: 'bakery'
  }, {
    id: 22,
    name: 'alface',
    unit_type: 'g',
    current_cost_per_unit: 0.0500,
    category: 'vegetables'
  }, {
    id: 23,
    name: 'tomate',
    unit_type: 'g',
    current_cost_per_unit: 0.0800,
    category: 'vegetables'
  }];
  const mockRecipes = [{
    id: 11,
    name: 'Produto 1 - Receita',
    cost: 1.8950,
    price: 25.00,
    margin: 0.9242,
    product_id: 15
  }, {
    id: 12,
    name: 'Produto 2 - Receita',
    cost: 1.6375,
    price: 22.00,
    margin: 0.9255,
    product_id: 16
  }, {
    id: 13,
    name: 'Produto 3 - Receita',
    cost: 0.0105,
    price: 15.00,
    margin: 0.9993,
    product_id: 17
  }];
  const mockVariations = [{
    category: 'protein',
    percentage_change: 8.7
  }, {
    category: 'dairy',
    percentage_change: 11.1
  }, {
    category: 'bakery',
    percentage_change: 7.1
  }, {
    category: 'vegetables',
    percentage_change: 11.1
  }];
  const mockAlerts = [{
    message: 'Laticínios variou +11.1%',
    value: 11.1,
    type: 'increase'
  }, {
    message: 'Vegetais variou +11.1%',
    value: 11.1,
    type: 'increase'
  }, {
    message: 'Proteína variou +8.7%',
    value: 8.7,
    type: 'increase'
  }];

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
      if (warnings.length) {
        setApiWarning(warnings.join(' | '));
        // Use mock data if API fails
        setUseMockData(true);
        setIngredients(mockIngredients);
        setRecipes(mockRecipes);
        setVariations(mockVariations);
        setAlerts(mockAlerts);
      } else {
        setIngredients(ingredientsRes.data.ingredients || []);
        setRecipes(recipesRes.data.recipes || []);
        const variations = variationsRes.data.variations || [];
        setVariations(variations);
        const newAlerts = variations.filter(v => Math.abs(v.percentage_change) > 5).map(v => ({
          message: `${getCategoryName(v.category)} variou ${v.percentage_change > 0 ? '+' : ''}${v.percentage_change.toFixed(1)}%`,
          value: v.percentage_change,
          type: v.percentage_change > 0 ? 'increase' : 'decrease'
        }));
        setAlerts(newAlerts);
      }
    } catch (error) {
      console.error('Error fetching data:', error);
      setApiWarning(error.message || 'Erro ao carregar dados');
      // Use mock data on error
      setUseMockData(true);
      setIngredients(mockIngredients);
      setRecipes(mockRecipes);
      setVariations(mockVariations);
      setAlerts(mockAlerts);
    } finally {
      setLoading(false);
    }
  };
  const handleCreateRecipe = async newRecipe => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/recipes`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(newRecipe)
      });
      if (response.ok) {
        fetchData();
      } else {
        // If API fails, add locally for demo
        const recipeWithId = {
          ...newRecipe,
          id: recipes.length + 1
        };
        setRecipes([...recipes, recipeWithId]);
      }
    } catch (error) {
      console.error('Error creating recipe:', error);
      // Add locally for demo
      const recipeWithId = {
        ...newRecipe,
        id: recipes.length + 1
      };
      setRecipes([...recipes, recipeWithId]);
    }
  };
  const handleCreateIngredient = async newIngredient => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/ingredients`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(newIngredient)
      });
      if (response.ok) {
        fetchData();
      } else {
        // If API fails, add locally for demo
        const ingredientWithId = {
          ...newIngredient,
          id: ingredients.length + 1
        };
        setIngredients([...ingredients, ingredientWithId]);
      }
    } catch (error) {
      console.error('Error creating ingredient:', error);
      // Add locally for demo
      const ingredientWithId = {
        ...newIngredient,
        id: ingredients.length + 1
      };
      setIngredients([...ingredients, ingredientWithId]);
    }
  };
  const handleEditIngredient = async updatedIngredient => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/ingredients/${updatedIngredient.id}`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(updatedIngredient)
      });
      if (response.ok) {
        fetchData();
      } else {
        // If API fails, update locally for demo
        setIngredients(ingredients.map(ing => ing.id === updatedIngredient.id ? updatedIngredient : ing));
      }
    } catch (error) {
      console.error('Error updating ingredient:', error);
      // Update locally for demo
      setIngredients(ingredients.map(ing => ing.id === updatedIngredient.id ? updatedIngredient : ing));
    }
  };
  const handleSaveCategory = async category => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/categories`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(category)
      });
      if (response.ok) {
        const data = await response.json();
        setCategories([...categories, data.category]);
      } else {
        // If API fails, add locally for demo
        const newCat = {
          id: categories.length + 1,
          ...category
        };
        setCategories([...categories, newCat]);
      }
    } catch (error) {
      console.error('Error saving category:', error);
      // Add locally for demo
      const newCat = {
        id: categories.length + 1,
        ...category
      };
      setCategories([...categories, newCat]);
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
  }, useMockData && /*#__PURE__*/React.createElement("span", {
    className: "me-mock-badge"
  }, "Modo Demonstra\xE7\xE3o"), /*#__PURE__*/React.createElement("button", {
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
  }, apiWarning && !useMockData && /*#__PURE__*/React.createElement("div", {
    className: "me-api-warning",
    role: "alert"
  }, apiWarning, ' ', /*#__PURE__*/React.createElement("a", {
    href: `${HOME_URL}`
  }, "Voltar ao painel")), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-card",
    style: {
      borderColor: COLORS.purple
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-header"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-icon",
    style: {
      color: COLORS.purple
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "package",
    size: 24
  })), /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-title"
  }, "Ingredientes")), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-value"
  }, ingredients.length), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-sm me-btn-secondary",
    onClick: () => setIsIngredientModalOpen(true),
    style: {
      marginTop: '8px'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 14,
    style: {
      marginRight: '4px'
    }
  }), "Novo")), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-card",
    style: {
      borderColor: COLORS.blue
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-header"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-icon",
    style: {
      color: COLORS.blue
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "book-open",
    size: 24
  })), /*#__PURE__*/React.createElement("span", {
    className: "me-kpi-title"
  }, "Receitas")), /*#__PURE__*/React.createElement("div", {
    className: "me-kpi-value"
  }, recipes.length), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-sm me-btn-secondary",
    onClick: () => setIsCreateModalOpen(true),
    style: {
      marginTop: '8px'
    }
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 14,
    style: {
      marginRight: '4px'
    }
  }), "Nova")), /*#__PURE__*/React.createElement(KPICard, {
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
    className: "me-ingredients-list-section"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-section-header"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "me-section-title"
  }, "Ingredientes"), /*#__PURE__*/React.createElement("button", {
    className: "me-btn me-btn-sm me-btn-secondary",
    onClick: () => setIsIngredientModalOpen(true)
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "plus",
    size: 14,
    style: {
      marginRight: '4px'
    }
  }), "Novo")), /*#__PURE__*/React.createElement("div", {
    className: "me-ingredients-grid"
  }, ingredients.map(ingredient => /*#__PURE__*/React.createElement("div", {
    key: ingredient.id,
    className: "me-ingredient-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "me-ingredient-info"
  }, /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-name"
  }, ingredient.name), /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-details"
  }, formatCurrency(ingredient.current_cost_per_unit), "/", ingredient.unit_type), /*#__PURE__*/React.createElement("span", {
    className: "me-ingredient-category"
  }, getCategoryName(ingredient.category))), /*#__PURE__*/React.createElement("button", {
    className: "me-btn-icon",
    onClick: () => {
      setSelectedIngredient(ingredient);
      setIsEditIngredientModalOpen(true);
    },
    title: "Editar"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "edit-2",
    size: 16
  })))))), /*#__PURE__*/React.createElement("div", {
    className: "me-charts-grid"
  }, /*#__PURE__*/React.createElement(CategoryChart, {
    data: variations
  })), /*#__PURE__*/React.createElement(RecipeTable, {
    recipes: recipes,
    onSelectRecipe: setSelectedRecipe,
    onCreateRecipe: () => setIsCreateModalOpen(true)
  })), selectedRecipe && /*#__PURE__*/React.createElement(RecipeDetailModal, {
    recipe: selectedRecipe,
    onClose: () => setSelectedRecipe(null)
  }), /*#__PURE__*/React.createElement(CreateRecipeModal, {
    isOpen: isCreateModalOpen,
    onClose: () => setIsCreateModalOpen(false),
    ingredients: ingredients,
    onSave: handleCreateRecipe
  }), /*#__PURE__*/React.createElement(CreateIngredientModal, {
    isOpen: isIngredientModalOpen,
    onClose: () => setIsIngredientModalOpen(false),
    onSave: handleCreateIngredient
  }), /*#__PURE__*/React.createElement(EditIngredientModal, {
    isOpen: isEditIngredientModalOpen,
    onClose: () => setIsEditIngredientModalOpen(false),
    ingredient: selectedIngredient,
    onSave: handleEditIngredient,
    categories: categories,
    onManageCategories: () => setIsCategoryModalOpen(true)
  }), /*#__PURE__*/React.createElement(CategoryModal, {
    isOpen: isCategoryModalOpen,
    onClose: () => setIsCategoryModalOpen(false),
    categories: categories,
    onSave: handleSaveCategory
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