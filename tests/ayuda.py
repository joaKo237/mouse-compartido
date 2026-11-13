"""Cosas que usan varias pruebas: dos PCs ya emparejadas, inventadas."""

from mouse_compartido.red.seguridad import Emparejamiento

ID_SERVIDOR = "11" * 16
ID_CLIENTE = "22" * 16
CLAVE = "ab" * 32

EMP_SERVIDOR = Emparejamiento(bytes.fromhex(ID_SERVIDOR), bytes.fromhex(ID_CLIENTE),
                              bytes.fromhex(CLAVE))
EMP_CLIENTE = Emparejamiento(bytes.fromhex(ID_CLIENTE), bytes.fromhex(ID_SERVIDOR),
                             bytes.fromhex(CLAVE))
# Una tercera PC que se emparejó con el servidor por su cuenta (otra clave).
EMP_INTRUSA = Emparejamiento(bytes.fromhex("33" * 16), bytes.fromhex(ID_SERVIDOR),
                             bytes.fromhex("cd" * 32))


def emparejada(rol, **otros):
    """Campos de Config para una PC con ese rol, ya emparejada con la otra."""
    if rol == "servidor":
        campos = dict(id_pc=ID_SERVIDOR, emparejado_id=ID_CLIENTE)
    else:
        campos = dict(id_pc=ID_CLIENTE, emparejado_id=ID_SERVIDOR)
    campos.update(rol=rol, emparejado_clave=CLAVE, emparejado_nombre="otra-pc")
    campos.update(otros)
    return campos
