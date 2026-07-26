const { useState, useEffect, useCallback } = React;
const RechartsLib = window.Recharts || {};
const { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } = RechartsLib;

// ==================== CONFIGURATION ====================
const API_BASE = window.ME_API_BASE || '';
const HOME_URL = window.ME_HOME || '/';
const fetchOpts = {
  credentials: 'same-origin',
  headers: {
    Accept: 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
};

const readApiError = async (response) => {
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

const fetchJson = async (url) => {
  const response = await fetch(url, fetchOpts);
  if (!response.ok) {
    return { ok: false, error: await readApiError(response), data: null };
  }
  try {
    return { ok: true, error: null, data: await response.json() };
  } catch (err) {
    return { ok: false, error: err.message || 'Resposta invalida da API', data: null };
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
  cyan: '#06b6d4',
};

const THEME = {
  dark: {
    bg: '#0f0f14',
    surface: '#1a1a28',
    surfaceHover: '#252538',
    border: '#2a2a40',
    text: '#e8e8f0',
    textMuted: '#888fa0',
    inputBg: '#10101a',
  },
  light: {
    bg: '#f1f5f9',
    surface: '#ffffff',
    surfaceHover: '#f8fafc',
    border: '#c8d0e0',
    text: '#0f172a',
    textMuted: '#64748b',
    inputBg: '#f8fafc',
  }
};

// ==================== UTILITIES ====================
const formatCurrency = (value) => {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL'
  }).format(value);
};

const formatPercent = (value) => {
  return `${(value * 100).toFixed(1)}%`;
};

const getMarginColor = (margin) => {
  if (margin > 0.4) return COLORS.green;
  if (margin > 0.2) return COLORS.yellow;
  return COLORS.red;
};

const getMarginLabel = (margin) => {
  if (margin > 0.4) return 'Excelente';
  if (margin > 0.2) return 'Boa';
  if (margin > 0) return 'Baixa';
  return 'Negativa';
};

// ==================== COMPONENTS ====================

// KPI Card Component
const KPICard = ({ title, value, trend, icon, color }) => {
  const isPositive = trend >= 0;
  return (
    <div className="me-kpi-card" style={{ borderColor: color }}>
      <div className="me-kpi-header">
        <span className="me-kpi-icon" style={{ color }}>{icon}</span>
        <span className="me-kpi-title">{title}</span>
      </div>
      <div className="me-kpi-value">{value}</div>
      {trend !== null && (
        <div className={`me-kpi-trend ${isPositive ? 'positive' : 'negative'}`}>
          {isPositive ? '↑' : '↓'} {Math.abs(trend).toFixed(1)}%
        </div>
      )}
    </div>
  );
};

// Upload Zone Component
const UploadZone = ({ onUpload, uploadedItems }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileSelect = (e) => {
    const files = e.target.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileUpload = async (file) => {
    setIsUploading(true);
    
    const text = await file.text();
    
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/import-xml`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ xml: text }),
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

  return (
    <div className="me-upload-section">
      <div 
        className={`me-upload-zone ${isDragging ? 'dragging' : ''} ${isUploading ? 'uploading' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="me-upload-content">
          <i data-lucide="upload-cloud" className="me-upload-icon"></i>
          <p className="me-upload-text">Arraste o XML da NF-e ou clique para selecionar</p>
          <p className="me-upload-subtext">Suporta arquivos .xml</p>
          <input 
            type="file" 
            accept=".xml" 
            onChange={handleFileSelect}
            className="me-upload-input"
            disabled={isUploading}
          />
          {!isUploading && (
            <button className="me-upload-btn">
              Selecionar Arquivo
            </button>
          )}
          {isUploading && (
            <div className="me-upload-progress">
              <div className="me-progress-bar"></div>
            </div>
          )}
        </div>
      </div>

      {uploadedItems.length > 0 && (
        <div className="me-upload-preview">
          <h4 className="me-preview-title">Itens Importados</h4>
          {uploadedItems.map((item, index) => (
            <div key={index} className="me-preview-item">
              <span className="me-preview-name">{item.name}</span>
              <span className="me-preview-cost">{formatCurrency(item.cost_per_unit)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// Alert Panel Component
const AlertPanel = ({ alerts }) => {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="me-alert-panel">
      <div className="me-alert-header">
        <i data-lucide="alert-triangle" className="me-alert-icon"></i>
        <h3 className="me-alert-title">Alertas de Preço</h3>
      </div>
      {alerts.map((alert, index) => (
        <div key={index} className="me-alert-item">
          <span className="me-alert-text">{alert.message}</span>
          <span className={`me-alert-badge ${alert.type}`}>
            {alert.type === 'increase' ? '↑' : '↓'} {Math.abs(alert.value).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
};

// Category Chart Component
const getCategoryColor = (category) => {
  const colors = {
    protein: COLORS.purple,
    dairy: COLORS.blue,
    bakery: COLORS.orange,
    vegetables: COLORS.green,
    other: COLORS.cyan,
  };
  return colors[String(category || '').toLowerCase()] || COLORS.purple;
};

const getCategoryName = (category) => {
  const names = {
    protein: 'Proteína',
    dairy: 'Laticínios',
    bakery: 'Padaria',
    vegetables: 'Vegetais',
    fruits: 'Frutas',
    spices: 'Temperos',
    other: 'Outros',
  };
  return names[String(category || '').toLowerCase()] || category;
};

const CategoryChartFallback = ({ data }) => {
  const maxValue = Math.max(...data.map((item) => Math.abs(item.percentage_change || 0)), 1);

  return (
    <div className="me-chart-fallback" role="img" aria-label="Variação por categoria">
      {data.map((item) => {
        const value = Number(item.percentage_change) || 0;
        const height = Math.max(4, (Math.abs(value) / maxValue) * 100);
        const color = getCategoryColor(item.category);
        const categoryName = getCategoryName(item.category);
        return (
          <div key={item.category} className="me-chart-fallback-bar">
            <span className="me-chart-fallback-value">{value >= 0 ? '+' : ''}{value.toFixed(1)}%</span>
            <div
              className="me-chart-fallback-fill"
              style={{ height: `${height}%`, backgroundColor: color }}
              title={`${categoryName}: ${value.toFixed(1)}%`}
            />
            <span className="me-chart-fallback-label">{categoryName}</span>
          </div>
        );
      })}
    </div>
  );
};

const CategoryChart = ({ data }) => {
  if (!data || data.length === 0) {
    return (
      <div className="me-chart-section">
        <h3 className="me-section-title">Variação por Categoria</h3>
        <p className="me-chart-empty">Sem dados ainda. Importe uma NF-e para começar.</p>
      </div>
    );
  }

  const chartData = data.map((item) => ({
    ...item,
    fill: getCategoryColor(item.category),
  }));

  if (!BarChart || !ResponsiveContainer) {
    return (
      <div className="me-chart-section">
        <h3 className="me-section-title">Variação por Categoria</h3>
        <CategoryChartFallback data={chartData} />
      </div>
    );
  }

  return (
    <div className="me-chart-section">
      <h3 className="me-section-title">Variação por Categoria</h3>
      <div className="me-chart-container">
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={chartData}>
            <XAxis
              dataKey="category"
              stroke="#888fa0"
              style={{ fontSize: '12px' }}
            />
            <YAxis
              stroke="#888fa0"
              style={{ fontSize: '12px' }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: THEME.dark.surface,
                border: `1px solid ${THEME.dark.border}`,
                borderRadius: '8px',
              }}
              itemStyle={{ color: THEME.dark.text }}
              formatter={(value) => [`${value.toFixed(1)}%`, 'Variação']}
            />
            <Bar dataKey="percentage_change" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

// Recipe Table Component
const RecipeTable = ({ recipes, onSelectRecipe, onCreateRecipe }) => {
  const [sortField, setSortField] = useState('name');
  const [sortDirection, setSortDirection] = useState('asc');
  const [searchTerm, setSearchTerm] = useState('');

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const handleViewDetails = async (recipe) => {
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

  const filteredRecipes = recipes
    .filter(recipe => 
      recipe.name.toLowerCase().includes(searchTerm.toLowerCase())
    )
    .sort((a, b) => {
      const aValue = a[sortField];
      const bValue = b[sortField];
      
      if (typeof aValue === 'string') {
        return sortDirection === 'asc' 
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue);
      }
      
      return sortDirection === 'asc' ? aValue - bValue : bValue - aValue;
    });

  return (
    <div className="me-recipes-section">
      <div className="me-section-header">
        <h3 className="me-section-title">Receitas</h3>
        <div className="me-section-actions">
          <button className="me-btn me-btn-primary" onClick={onCreateRecipe}>
            <i data-lucide="plus" size={16} style={{ marginRight: '8px' }}></i>
            Nova Receita
          </button>
          <div className="me-search-box">
            <i data-lucide="search" className="me-search-icon"></i>
            <input
              type="text"
              placeholder="Buscar receitas..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="me-search-input"
            />
          </div>
        </div>
      </div>

      <div className="me-table-container">
        <table className="me-table">
          <thead>
            <tr>
              <th onClick={() => handleSort('name')}>
                Nome {sortField === 'name' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th onClick={() => handleSort('cost')}>
                Custo {sortField === 'cost' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th onClick={() => handleSort('price')}>
                Preço {sortField === 'price' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th onClick={() => handleSort('margin')}>
                Margem {sortField === 'margin' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {filteredRecipes.length === 0 ? (
              <tr>
                <td colSpan="5" className="me-table-empty">
                  <div className="me-empty-table">
                    <i data-lucide="book-open" size={48} style={{ color: COLORS.cyan }}></i>
                    <p>Nenhuma receita encontrada</p>
                    <button className="me-btn me-btn-secondary" onClick={onCreateRecipe}>
                      Criar primeira receita
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              filteredRecipes.map(recipe => (
                <tr key={recipe.id} className="me-table-row">
                  <td className="me-table-name">{recipe.name}</td>
                  <td className="me-table-cost">{formatCurrency(recipe.cost)}</td>
                  <td className="me-table-price">{formatCurrency(recipe.price)}</td>
                  <td className="me-table-margin">
                    <span 
                      className="me-margin-badge"
                      style={{ 
                        backgroundColor: getMarginColor(recipe.margin) + '20', 
                        color: getMarginColor(recipe.margin) 
                      }}
                    >
                      {formatPercent(recipe.margin)}
                    </span>
                  </td>
                  <td className="me-table-actions">
                    <button 
                      className="me-btn-icon"
                      onClick={() => handleViewDetails(recipe)}
                      title="Ver detalhes"
                    >
                      <i data-lucide="eye" size={16}></i>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// Recipe Detail Modal Component
const RecipeDetailModal = ({ recipe, onClose }) => {
  if (!recipe) return null;

  return (
    <div className="me-modal-overlay" onClick={onClose}>
      <div className="me-modal" onClick={(e) => e.stopPropagation()}>
        <div className="me-modal-header">
          <h3 className="me-modal-title">{recipe.recipe_name}</h3>
          <button className="me-modal-close" onClick={onClose}>
            <i data-lucide="x" size={20}></i>
          </button>
        </div>
        
        <div className="me-modal-content">
          <div className="me-modal-summary">
            <div className="me-summary-item">
              <span className="me-summary-label">Custo Total</span>
              <span className="me-summary-value">{formatCurrency(recipe.cost)}</span>
            </div>
            <div className="me-summary-item">
              <span className="me-summary-label">Preço de Venda</span>
              <span className="me-summary-value">{formatCurrency(recipe.price)}</span>
            </div>
            <div className="me-summary-item">
              <span className="me-summary-label">Margem</span>
              <span 
                className="me-summary-value me-margin-value"
                style={{ color: getMarginColor(recipe.margin) }}
              >
                {formatPercent(recipe.margin)}
              </span>
            </div>
          </div>

          <h4 className="me-modal-subtitle">Ingredientes</h4>
          <div className="me-ingredients-list">
            {recipe.ingredients && recipe.ingredients.map((ing, index) => (
              <div key={index} className="me-ingredient-item">
                <span className="me-ingredient-name">{ing.name}</span>
                <span className="me-ingredient-qty">{ing.qty}</span>
                <span className="me-ingredient-cost">{formatCurrency(ing.cost)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="me-modal-footer">
          <button className="me-btn me-btn-secondary" onClick={onClose}>
            Fechar
          </button>
          <button className="me-btn me-btn-primary">
            <i data-lucide="printer" size={16} style={{ marginRight: '8px' }}></i>
            Imprimir
          </button>
        </div>
      </div>
    </div>
  );
};

// Create Ingredient Modal Component
const CreateIngredientModal = ({ isOpen, onClose, onSave }) => {
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
        category: category,
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

  return (
    <div className="me-modal-overlay" onClick={onClose}>
      <div className="me-modal" onClick={(e) => e.stopPropagation()}>
        <div className="me-modal-header">
          <h3 className="me-modal-title">Novo Ingrediente</h3>
          <button className="me-modal-close" onClick={onClose}>
            <i data-lucide="x" size={20}></i>
          </button>
        </div>
        
        <div className="me-modal-content">
          <div className="me-form-group">
            <label className="me-form-label">Nome do Ingrediente *</label>
            <input
              type="text"
              className="me-form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: carne moída"
            />
          </div>

          <div className="me-form-row">
            <div className="me-form-group">
              <label className="me-form-label">Unidade de Medida</label>
              <select
                className="me-form-select"
                value={unitType}
                onChange={(e) => setUnitType(e.target.value)}
              >
                <option value="g">Gramas (g)</option>
                <option value="kg">Quilogramas (kg)</option>
                <option value="ml">Mililitros (ml)</option>
                <option value="l">Litros (l)</option>
                <option value="unit">Unidade (unit)</option>
              </select>
            </div>
            <div className="me-form-group">
              <label className="me-form-label">Categoria</label>
              <select
                className="me-form-select"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="protein">Proteína</option>
                <option value="dairy">Laticínios</option>
                <option value="bakery">Padaria</option>
                <option value="vegetables">Vegetais</option>
                <option value="fruits">Frutas</option>
                <option value="spices">Temperos</option>
                <option value="other">Outro</option>
              </select>
            </div>
          </div>

          <div className="me-form-group">
            <label className="me-form-label">Custo por Unidade (R$) *</label>
            <input
              type="number"
              step="0.0001"
              min="0"
              className="me-form-input"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              placeholder="Ex: 0.2500"
            />
          </div>
        </div>

        <div className="me-modal-footer">
          <button className="me-btn me-btn-secondary" onClick={onClose}>
            Cancelar
          </button>
          <button 
            className="me-btn me-btn-primary" 
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Salvando...' : 'Salvar Ingrediente'}
          </button>
        </div>
      </div>
    </div>
  );
};

// Edit Ingredient Modal Component
const EditIngredientModal = ({ isOpen, onClose, ingredient, onSave, categories, onManageCategories }) => {
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
        category: category,
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

  return (
    <div className="me-modal-overlay" onClick={onClose}>
      <div className="me-modal" onClick={(e) => e.stopPropagation()}>
        <div className="me-modal-header">
          <h3 className="me-modal-title">Editar Ingrediente</h3>
          <button className="me-modal-close" onClick={onClose}>
            <i data-lucide="x" size={20}></i>
          </button>
        </div>
        
        <div className="me-modal-content">
          <div className="me-form-group">
            <label className="me-form-label">Nome do Ingrediente *</label>
            <input
              type="text"
              className="me-form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: carne moída"
            />
          </div>

          <div className="me-form-row">
            <div className="me-form-group">
              <label className="me-form-label">Unidade de Medida</label>
              <select
                className="me-form-select"
                value={unitType}
                onChange={(e) => setUnitType(e.target.value)}
              >
                <option value="g">Gramas (g)</option>
                <option value="kg">Quilogramas (kg)</option>
                <option value="ml">Mililitros (ml)</option>
                <option value="l">Litros (l)</option>
                <option value="unit">Unidade (unit)</option>
              </select>
            </div>
            <div className="me-form-group">
              <label className="me-form-label">Categoria</label>
              <div style={{ display: 'flex', gap: '4px' }}>
                <select
                  className="me-form-select"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  style={{ flex: 1 }}
                >
                  <option value="protein">Proteína</option>
                  <option value="dairy">Laticínios</option>
                  <option value="bakery">Padaria</option>
                  <option value="vegetables">Vegetais</option>
                  <option value="fruits">Frutas</option>
                  <option value="spices">Temperos</option>
                  <option value="other">Outro</option>
                  {categories.map(cat => (
                    <option key={cat.id} value={cat.slug}>{cat.name}</option>
                  ))}
                </select>
                <button 
                  className="me-btn-icon" 
                  onClick={onManageCategories}
                  title="Gerenciar categorias"
                >
                  <i data-lucide="settings" size={16}></i>
                </button>
              </div>
            </div>
          </div>

          <div className="me-form-group">
            <label className="me-form-label">Custo por Unidade (R$) *</label>
            <input
              type="number"
              step="0.0001"
              min="0"
              className="me-form-input"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              placeholder="Ex: 0.2500"
            />
          </div>
        </div>

        <div className="me-modal-footer">
          <button className="me-btn me-btn-secondary" onClick={onClose}>
            Cancelar
          </button>
          <button 
            className="me-btn me-btn-primary" 
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Salvando...' : 'Salvar Alterações'}
          </button>
        </div>
      </div>
    </div>
  );
};

// Category Management Modal Component
const CategoryModal = ({ isOpen, onClose, categories, onSave }) => {
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
      await onSave({ name: newCategory.trim(), slug: slug });
      setNewCategory('');
    } catch (error) {
      console.error('Error adding category:', error);
      alert('Erro ao adicionar categoria');
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="me-modal-overlay" onClick={onClose}>
      <div className="me-modal" onClick={(e) => e.stopPropagation()}>
        <div className="me-modal-header">
          <h3 className="me-modal-title">Gerenciar Categorias</h3>
          <button className="me-modal-close" onClick={onClose}>
            <i data-lucide="x" size={20}></i>
          </button>
        </div>
        
        <div className="me-modal-content">
          <div className="me-form-group">
            <label className="me-form-label">Nova Categoria</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                className="me-form-input"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                placeholder="Ex: Bebidas"
                onKeyPress={(e) => e.key === 'Enter' && handleAddCategory()}
              />
              <button 
                className="me-btn me-btn-primary" 
                onClick={handleAddCategory}
                disabled={isSaving}
              >
                <i data-lucide="plus" size={16}></i>
              </button>
            </div>
          </div>

          <div className="me-categories-list">
            <h4 className="me-modal-subtitle">Categorias Padrão</h4>
            <div className="me-category-item">
              <span>Proteína</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Laticínios</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Padaria</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Vegetais</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Frutas</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Temperos</span>
              <span className="me-category-badge">Padrão</span>
            </div>
            <div className="me-category-item">
              <span>Outro</span>
              <span className="me-category-badge">Padrão</span>
            </div>

            {categories.length > 0 && (
              <>
                <h4 className="me-modal-subtitle" style={{ marginTop: '16px' }}>Categorias Personalizadas</h4>
                {categories.map(cat => (
                  <div key={cat.id} className="me-category-item">
                    <span>{cat.name}</span>
                    <span className="me-category-badge me-category-badge-custom">Personalizada</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="me-modal-footer">
          <button className="me-btn me-btn-secondary" onClick={onClose}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
};

// Create Recipe Modal Component
const CreateRecipeModal = ({ isOpen, onClose, ingredients, onSave }) => {
  const [recipeName, setRecipeName] = useState('');
  const [productId, setProductId] = useState('');
  const [sellingPrice, setSellingPrice] = useState('');
  const [selectedIngredients, setSelectedIngredients] = useState([]);
  const [isSaving, setIsSaving] = useState(false);

  const addIngredient = () => {
    setSelectedIngredients([...selectedIngredients, { ingredient_id: '', quantity: '' }]);
  };

  const removeIngredient = (index) => {
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
        return total + (ingredient.current_cost_per_unit * parseFloat(ing.quantity));
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
      const price = parseFloat(sellingPrice) || (totalCost * 1.3);
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

  return (
    <div className="me-modal-overlay" onClick={onClose}>
      <div className="me-modal me-modal-large" onClick={(e) => e.stopPropagation()}>
        <div className="me-modal-header">
          <h3 className="me-modal-title">Nova Receita</h3>
          <button className="me-modal-close" onClick={onClose}>
            <i data-lucide="x" size={20}></i>
          </button>
        </div>
        
        <div className="me-modal-content">
          <div className="me-form-group">
            <label className="me-form-label">Nome da Receita *</label>
            <input
              type="text"
              className="me-form-input"
              value={recipeName}
              onChange={(e) => setRecipeName(e.target.value)}
              placeholder="Ex: Burger Classic"
            />
          </div>

          <div className="me-form-row">
            <div className="me-form-group">
              <label className="me-form-label">ID do Produto (opcional)</label>
              <input
                type="number"
                className="me-form-input"
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
                placeholder="ID do produto no sistema"
              />
            </div>
            <div className="me-form-group">
              <label className="me-form-label">Preço de Venda (R$)</label>
              <input
                type="number"
                step="0.01"
                className="me-form-input"
                value={sellingPrice}
                onChange={(e) => setSellingPrice(e.target.value)}
                placeholder="Auto-calculado se vazio"
              />
            </div>
          </div>

          <div className="me-ingredients-section">
            <div className="me-section-header">
              <h4 className="me-modal-subtitle">Ingredientes</h4>
              <button className="me-btn me-btn-sm me-btn-secondary" onClick={addIngredient}>
                <i data-lucide="plus" size={16} style={{ marginRight: '4px' }}></i>
                Adicionar
              </button>
            </div>

            {selectedIngredients.length === 0 ? (
              <p className="me-empty-state">Nenhum ingrediente adicionado. Clique em "Adicionar" para começar.</p>
            ) : (
              <div className="me-recipe-ingredients-list">
                {selectedIngredients.map((ing, index) => (
                  <div key={index} className="me-recipe-ingredient-row">
                    <select
                      className="me-form-select"
                      value={ing.ingredient_id}
                      onChange={(e) => updateIngredient(index, 'ingredient_id', e.target.value)}
                    >
                      <option value="">Selecione um ingrediente</option>
                      {ingredients.map(ingredient => (
                        <option key={ingredient.id} value={ingredient.id}>
                          {ingredient.name} ({formatCurrency(ingredient.current_cost_per_unit)}/{ingredient.unit_type})
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      step="0.01"
                      className="me-form-input me-form-input-sm"
                      placeholder="Qtd"
                      value={ing.quantity}
                      onChange={(e) => updateIngredient(index, 'quantity', e.target.value)}
                    />
                    <button
                      className="me-btn-icon me-btn-icon-danger"
                      onClick={() => removeIngredient(index)}
                      title="Remover"
                    >
                      <i data-lucide="trash-2" size={16}></i>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {selectedIngredients.length > 0 && (
            <div className="me-cost-preview">
              <div className="me-cost-item">
                <span className="me-cost-label">Custo Total Estimado:</span>
                <span className="me-cost-value">{formatCurrency(calculateTotalCost())}</span>
              </div>
              {sellingPrice && (
                <div className="me-cost-item">
                  <span className="me-cost-label">Margem Estimada:</span>
                  <span 
                    className="me-cost-value"
                    style={{ color: getMarginColor((parseFloat(sellingPrice) - calculateTotalCost()) / parseFloat(sellingPrice)) }}
                  >
                    {formatPercent((parseFloat(sellingPrice) - calculateTotalCost()) / parseFloat(sellingPrice))}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="me-modal-footer">
          <button className="me-btn me-btn-secondary" onClick={onClose}>
            Cancelar
          </button>
          <button 
            className="me-btn me-btn-primary" 
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Salvando...' : 'Salvar Receita'}
          </button>
        </div>
      </div>
    </div>
  );
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
  const mockIngredients = [
    { id: 19, name: 'carne moída', unit_type: 'g', current_cost_per_unit: 0.2500, category: 'protein' },
    { id: 20, name: 'queijo', unit_type: 'g', current_cost_per_unit: 0.6667, category: 'dairy' },
    { id: 21, name: 'pão', unit_type: 'unit', current_cost_per_unit: 1.5000, category: 'bakery' },
    { id: 22, name: 'alface', unit_type: 'g', current_cost_per_unit: 0.0500, category: 'vegetables' },
    { id: 23, name: 'tomate', unit_type: 'g', current_cost_per_unit: 0.0800, category: 'vegetables' },
  ];

  const mockRecipes = [
    {
      id: 11,
      name: 'Produto 1 - Receita',
      cost: 1.8950,
      price: 25.00,
      margin: 0.9242,
      product_id: 15,
    },
    {
      id: 12,
      name: 'Produto 2 - Receita',
      cost: 1.6375,
      price: 22.00,
      margin: 0.9255,
      product_id: 16,
    },
    {
      id: 13,
      name: 'Produto 3 - Receita',
      cost: 0.0105,
      price: 15.00,
      margin: 0.9993,
      product_id: 17,
    },
  ];

  const mockVariations = [
    { category: 'protein', percentage_change: 8.7 },
    { category: 'dairy', percentage_change: 11.1 },
    { category: 'bakery', percentage_change: 7.1 },
    { category: 'vegetables', percentage_change: 11.1 },
  ];

  const mockAlerts = [
    { message: 'Laticínios variou +11.1%', value: 11.1, type: 'increase' },
    { message: 'Vegetais variou +11.1%', value: 11.1, type: 'increase' },
    { message: 'Proteína variou +8.7%', value: 8.7, type: 'increase' },
  ];

  // Fetch data on mount
  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setApiWarning('');

      const [ingredientsRes, recipesRes, variationsRes] = await Promise.all([
        fetchJson(`${API_BASE}/menu-engineering/ingredients`),
        fetchJson(`${API_BASE}/menu-engineering/recipes`),
        fetchJson(`${API_BASE}/menu-engineering/category-variation`),
      ]);

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

        const newAlerts = variations
          .filter(v => Math.abs(v.percentage_change) > 5)
          .map(v => ({
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

  const handleCreateRecipe = async (newRecipe) => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/recipes`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(newRecipe),
      });

      if (response.ok) {
        fetchData();
      } else {
        // If API fails, add locally for demo
        const recipeWithId = {
          ...newRecipe,
          id: recipes.length + 1,
        };
        setRecipes([...recipes, recipeWithId]);
      }
    } catch (error) {
      console.error('Error creating recipe:', error);
      // Add locally for demo
      const recipeWithId = {
        ...newRecipe,
        id: recipes.length + 1,
      };
      setRecipes([...recipes, recipeWithId]);
    }
  };

  const handleCreateIngredient = async (newIngredient) => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/ingredients`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(newIngredient),
      });

      if (response.ok) {
        fetchData();
      } else {
        // If API fails, add locally for demo
        const ingredientWithId = {
          ...newIngredient,
          id: ingredients.length + 1,
        };
        setIngredients([...ingredients, ingredientWithId]);
      }
    } catch (error) {
      console.error('Error creating ingredient:', error);
      // Add locally for demo
      const ingredientWithId = {
        ...newIngredient,
        id: ingredients.length + 1,
      };
      setIngredients([...ingredients, ingredientWithId]);
    }
  };

  const handleEditIngredient = async (updatedIngredient) => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/ingredients/${updatedIngredient.id}`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(updatedIngredient),
      });

      if (response.ok) {
        fetchData();
      } else {
        // If API fails, update locally for demo
        setIngredients(ingredients.map(ing => 
          ing.id === updatedIngredient.id ? updatedIngredient : ing
        ));
      }
    } catch (error) {
      console.error('Error updating ingredient:', error);
      // Update locally for demo
      setIngredients(ingredients.map(ing => 
        ing.id === updatedIngredient.id ? updatedIngredient : ing
      ));
    }
  };

  const handleSaveCategory = async (category) => {
    try {
      const response = await fetch(`${API_BASE}/menu-engineering/categories`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify(category),
      });

      if (response.ok) {
        const data = await response.json();
        setCategories([...categories, data.category]);
      } else {
        // If API fails, add locally for demo
        const newCat = { id: categories.length + 1, ...category };
        setCategories([...categories, newCat]);
      }
    } catch (error) {
      console.error('Error saving category:', error);
      // Add locally for demo
      const newCat = { id: categories.length + 1, ...category };
      setCategories([...categories, newCat]);
    }
  };

  // Calculate KPIs
  const avgMargin = recipes.length > 0
    ? recipes.reduce((sum, r) => sum + r.margin, 0) / recipes.length
    : 0;

  // Initialize Lucide icons
  useEffect(() => {
    if (window.lucide) {
      window.lucide.createIcons();
    }
  });

  if (loading) {
    return (
      <div className="me-loading">
        <div className="me-spinner"></div>
        <p>Carregando...</p>
      </div>
    );
  }

  return (
    <div className="me-container">
      {/* Header */}
      <header className="me-header">
        <div className="me-header-left">
          <a href={HOME_URL} className="me-home-btn">
            <i data-lucide="home" size={18}></i>
          </a>
          <div className="me-brand">
            <i data-lucide="chef-hat" size={24} style={{ color: COLORS.purple }}></i>
            <h1>Custos &amp; Margens</h1>
          </div>
        </div>
        <div className="me-header-right">
          {useMockData && (
            <span className="me-mock-badge">Modo Demonstração</span>
          )}
          <button className="me-theme-toggle" id="theme-toggle">
            <i data-lucide="sun" className="icon-light" size={18}></i>
            <i data-lucide="moon" className="icon-dark" size={18}></i>
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="me-main">
        {apiWarning && !useMockData && (
          <div className="me-api-warning" role="alert">
            {apiWarning}
            {' '}
            <a href={`${HOME_URL}`}>Voltar ao painel</a>
          </div>
        )}
        {/* KPI Cards */}
        <div className="me-kpi-grid">
          <div className="me-kpi-card" style={{ borderColor: COLORS.purple }}>
            <div className="me-kpi-header">
              <span className="me-kpi-icon" style={{ color: COLORS.purple }}><i data-lucide="package" size={24}></i></span>
              <span className="me-kpi-title">Ingredientes</span>
            </div>
            <div className="me-kpi-value">{ingredients.length}</div>
            <button className="me-btn me-btn-sm me-btn-secondary" onClick={() => setIsIngredientModalOpen(true)} style={{ marginTop: '8px' }}>
              <i data-lucide="plus" size={14} style={{ marginRight: '4px' }}></i>
              Novo
            </button>
          </div>
          <div className="me-kpi-card" style={{ borderColor: COLORS.blue }}>
            <div className="me-kpi-header">
              <span className="me-kpi-icon" style={{ color: COLORS.blue }}><i data-lucide="book-open" size={24}></i></span>
              <span className="me-kpi-title">Receitas</span>
            </div>
            <div className="me-kpi-value">{recipes.length}</div>
            <button className="me-btn me-btn-sm me-btn-secondary" onClick={() => setIsCreateModalOpen(true)} style={{ marginTop: '8px' }}>
              <i data-lucide="plus" size={14} style={{ marginRight: '4px' }}></i>
              Nova
            </button>
          </div>
          <KPICard 
            title="Margem Média"
            value={formatPercent(avgMargin)}
            trend={avgMargin * 100}
            icon={<i data-lucide="trending-up" size={24}></i>}
            color={avgMargin > 0.2 ? COLORS.green : COLORS.red}
          />
        </div>

        {/* Upload and Alerts */}
        <div className="me-top-grid">
          <UploadZone onUpload={(data) => {
            setUploadedItems(data.imported_items || []);
            fetchData();
          }} uploadedItems={uploadedItems} />
          <AlertPanel alerts={alerts} />
        </div>

        {/* Ingredients List */}
        <div className="me-ingredients-list-section">
          <div className="me-section-header">
            <h3 className="me-section-title">Ingredientes</h3>
            <button className="me-btn me-btn-sm me-btn-secondary" onClick={() => setIsIngredientModalOpen(true)}>
              <i data-lucide="plus" size={14} style={{ marginRight: '4px' }}></i>
              Novo
            </button>
          </div>
          <div className="me-ingredients-grid">
            {ingredients.map(ingredient => (
              <div key={ingredient.id} className="me-ingredient-card">
                <div className="me-ingredient-info">
                  <span className="me-ingredient-name">{ingredient.name}</span>
                  <span className="me-ingredient-details">
                    {formatCurrency(ingredient.current_cost_per_unit)}/{ingredient.unit_type}
                  </span>
                  <span className="me-ingredient-category">{getCategoryName(ingredient.category)}</span>
                </div>
                <button 
                  className="me-btn-icon"
                  onClick={() => {
                    setSelectedIngredient(ingredient);
                    setIsEditIngredientModalOpen(true);
                  }}
                  title="Editar"
                >
                  <i data-lucide="edit-2" size={16}></i>
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Charts */}
        <div className="me-charts-grid">
          <CategoryChart data={variations} />
        </div>

        {/* Recipes Table */}
        <RecipeTable 
          recipes={recipes} 
          onSelectRecipe={setSelectedRecipe}
          onCreateRecipe={() => setIsCreateModalOpen(true)}
        />
      </main>

      {/* Recipe Detail Modal */}
      {selectedRecipe && (
        <RecipeDetailModal recipe={selectedRecipe} onClose={() => setSelectedRecipe(null)} />
      )}

      {/* Create Recipe Modal */}
      <CreateRecipeModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        ingredients={ingredients}
        onSave={handleCreateRecipe}
      />

      {/* Create Ingredient Modal */}
      <CreateIngredientModal
        isOpen={isIngredientModalOpen}
        onClose={() => setIsIngredientModalOpen(false)}
        onSave={handleCreateIngredient}
      />

      {/* Edit Ingredient Modal */}
      <EditIngredientModal
        isOpen={isEditIngredientModalOpen}
        onClose={() => setIsEditIngredientModalOpen(false)}
        ingredient={selectedIngredient}
        onSave={handleEditIngredient}
        categories={categories}
        onManageCategories={() => setIsCategoryModalOpen(true)}
      />

      {/* Category Management Modal */}
      <CategoryModal
        isOpen={isCategoryModalOpen}
        onClose={() => setIsCategoryModalOpen(false)}
        categories={categories}
        onSave={handleSaveCategory}
      />
    </div>
  );
};

// Render
const rootEl = document.getElementById('root');
if (!window.React || !window.ReactDOM) {
  if (rootEl) {
    rootEl.innerHTML = '<div class="me-loading"><p>Não foi possível carregar a interface. Recarregue a página (Ctrl+F5).</p><p><a href="' + HOME_URL + '">Voltar ao painel</a></p></div>';
  }
} else {
  const root = ReactDOM.createRoot(rootEl);
  root.render(<MenuEngineering />);
}
