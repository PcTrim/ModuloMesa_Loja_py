
/* FUNÇÃO PARA BUSCAR CLIENTE POR TELEFONE */
function buscarCliente() {
    const telefone = document.getElementById('telefoneCliente').value.trim();
    const resultadoDiv = document.getElementById('resultado-cliente');
    
    if (!telefone) {
        resultadoDiv.innerHTML = '<p style="color:red;">Por favor, digite um telefone.</p>';
        return;
    }
    
    fetch(`/buscar-cliente?telefone=${encodeURIComponent(telefone)}`)
        .then(res => res.json())
        .then(data => {
            if (data.erro) {
                resultadoDiv.innerHTML = `<p style="color:red;"><b>Erro:</b> ${data.erro}</p>`;
            } else {
                let html = '<div style="background:#f0f0f0; padding:10px; border-radius:6px;">';
                html += `<p><b>Nome:</b> ${data.nome || 'N/A'}</p>`;
                html += `<p><b>Telefone:</b> ${data.telefone || 'N/A'}</p>`;
                if (data.endereco) html += `<p><b>Endereço:</b> ${data.endereco}</p>`;
                if (data.email) html += `<p><b>Email:</b> ${data.email}</p>`;
                html += '</div>';
                resultadoDiv.innerHTML = html;
            }
        })
        .catch(err => {
            console.error('Erro ao buscar cliente:', err);
            resultadoDiv.innerHTML = `<p style="color:red;">Erro na busca: ${err}</p>`;
        });
}
