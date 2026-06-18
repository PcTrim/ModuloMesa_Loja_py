console.log('JS casa.js carregado');

function abrirModalFormaPagamento() {
    document.getElementById('modalFormaPagamento').style.display = 'flex';
    carregarFormasPagamento();
}

function fecharModalFormaPagamento() {
    document.getElementById('modalFormaPagamento').style.display = 'none';
}

function carregarFormasPagamento() {
    fetch('/api/formas-pagamento', { credentials: 'include' })
        .then(async response => {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                console.log('Retorno formas de pagamento:', data);
                const lista = document.getElementById('listaFormaPagamento');
                if (data.sucesso) {
                    if (data.formas.length === 0) {
                        lista.innerHTML = '<p style="color: #999; text-align: center;">Nenhuma forma de pagamento cadastrada</p>';
                    } else {
                        lista.innerHTML = data.formas.map(forma => `
                            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px; border-bottom: 1px solid #eee;">
                                <span>${forma.forma}</span>
                                <button onclick="excluirFormaPagamento(${forma.chave})" style="padding: 5px 10px; background: #f56565; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 12px;">Excluir</button>
                            </div>
                        `).join('');
                    }
                } else {
                    alert('Erro ao carregar formas de pagamento: ' + data.mensagem);
                }
            } else {
                // Se não for JSON, provavelmente é HTML de redirecionamento
                alert('Sessão expirada ou não autenticada. Faça login novamente.');
                fecharModalFormaPagamento();
            }
        })
        .catch(error => {
            console.error('Erro:', error);
            alert('Erro ao carregar formas de pagamento');
        });
}

function adicionarFormaPagamento() {
    const input = document.getElementById('inputFormaPagamento');
    const forma = input.value.trim();

    if (!forma) {
        alert('Por favor, digite uma forma de pagamento');
        return;
    }

    fetch('/api/salvar-forma-pagamento', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ forma: forma })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            input.value = '';
            carregarFormasPagamento();
        } else {
            alert('Erro: ' + data.mensagem);
        }
    })
    .catch(error => {
        console.error('Erro:', error);
        alert('Erro ao adicionar forma de pagamento');
    });
}

function excluirFormaPagamento(chave) {
    if (!confirm('Tem certeza que deseja excluir esta forma de pagamento?')) {
        return;
    }

    fetch(`/api/excluir-forma-pagamento/${chave}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            carregarFormasPagamento();
        } else {
            alert('Erro: ' + data.mensagem);
        }
    })
    .catch(error => {
        console.error('Erro:', error);
        alert('Erro ao excluir forma de pagamento');
    });
}

document.addEventListener('click', function(event) {
    const modal = document.getElementById('modalFormaPagamento');
    if (event.target === modal) {
        fecharModalFormaPagamento();
    }
});

window.abrirModalFormaPagamento = abrirModalFormaPagamento;
window.fecharModalFormaPagamento = fecharModalFormaPagamento;
window.carregarFormasPagamento = carregarFormasPagamento;
window.adicionarFormaPagamento = adicionarFormaPagamento;
window.excluirFormaPagamento = excluirFormaPagamento;
