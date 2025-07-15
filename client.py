import pygame
import socket
import json
import threading
import sys
import time
import random

# --- Configuración de Pygame ---
pygame.init()

# Dimensiones de la ventana
WIDTH, HEIGHT = 1200, 600
SCREEN = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Simulador de Puente de Coches")

# Colores
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
LIGHT_GRAY = (230, 230, 230)
DARK_GRAY = (100, 100, 100)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
GREEN = (0, 200, 0)
PURPUL= (128, 0, 128)
ACTIVE_COLOR = (150, 150, 255) # Color para InputBox activo
SELECTED_DIRECTION_COLOR = (0, 200, 0) # Verde para la dirección seleccionada

# Fuentes
FONT = pygame.font.Font(None, 28)
TITLE_FONT = pygame.font.Font(None, 40)
HIGHLIGHT_FONT = pygame.font.Font(None, 32) # Para el auto cruzando

# --- Configuración de la Comunicación (Debe coincidir con el Backend Go) ---
HOST = 'localhost'
PORT = 12345

MSG_CAR_STATUS = "CAR_STATUS"
MSG_CAR_END = "CAR_END"
MSG_CAR_START = "CAR_START"
MSG_CONNECTED = "CONNECTED"
MSG_REQUEST_BRIDGE_ACCESS = "REQUEST_BRIDGE_ACCESS"

MSG_CHANGE_CAR_PROPERTIES = "CHANGE_CAR_PROPERTIES"
MSG_CHANGE_CAR_PROPERTIES_ACK = "CHANGE_CAR_PROPERTIES_ACK"

MSG_END_CONNECTION = "END_CONNECTION"
MSG_RECONNECT = "RECONNECT"

DIRECTION_NONE = "NONE"
DIRECTION_EAST_WEST = "EAST_TO_WEST"
DIRECTION_WEST_EAST = "WEST_TO_EAST"
CAR_STATE_WAITING = "WAITING"
CAR_STATE_CROSSING = "CROSSING"
CAR_STATE_COOLDOWN = "COOLDOWN"

LENGTH_BRIDGE = 300 # Longitud lógica del puente del backend

# --- Variables Globales para el Estado del Cliente y la UI ---
client_socket = None
network_thread = None
is_connected = False
assigned_client_id = "" # Ahora se inicializa vacío, se asignará al conectar/reconectar
all_cars_status = {}
car_status_lock = threading.Lock()

client_colors = {}
PREDEFINED_COLORS = [
    (255, 99, 71), (60, 179, 113), (255, 215, 0), (138, 43, 226), (0, 191, 255),
    (255, 165, 0), (218, 112, 214), (0, 128, 0), (128, 0, 0), (70, 130, 180)
]
color_index = 0

# Estado de reconexión
reconnect_attempts = 0
MAX_RECONNECT_ATTEMPTS = 5 # Cuántos reintentos automáticos
RECONNECT_DELAY = 2 # Segundos entre reintentos
reconnect_timer = 0 # Para controlar el tiempo entre reintentos

# Mapeo de direcciones para la UI
DIRECTION_LABELS = {
    DIRECTION_EAST_WEST: "ESTE A OESTE",
    DIRECTION_WEST_EAST: "OESTE A ESTE",
    "NONE": "N/A"
}

def get_unique_color(client_id):
    global color_index
    if client_id not in client_colors:
        if color_index < len(PREDEFINED_COLORS):
            client_colors[client_id] = PREDEFINED_COLORS[color_index]
            color_index += 1
        else:
            client_colors[client_id] = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
    return client_colors[client_id]

# --- Clases de Elementos de UI ---

class InputBox:
    def __init__(self, x, y, w, h, text='', placeholder='', is_numeric=False):
        self.rect = pygame.Rect(x, y, w, h)
        self.color = DARK_GRAY
        self.text = text
        self.placeholder = placeholder
        self.active = False
        self.is_numeric = is_numeric
        self.txt_surface = FONT.render(text if text else placeholder, True, BLACK if text else GRAY)
        self.enabled = True

    def handle_event(self, event):
        if not self.enabled:
            return None

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.active = True
            else:
                self.active = False
            self.color = ACTIVE_COLOR if self.active else DARK_GRAY
        
        if event.type == pygame.KEYDOWN:
            if self.active:
                if event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                elif event.key == pygame.K_RETURN:
                    self.active = False
                    self.color = DARK_GRAY
                else:
                    if self.is_numeric:
                        if event.unicode.isdigit():
                            self.text += event.unicode
                    else:
                        self.text += event.unicode
                self.txt_surface = FONT.render(self.text if self.text else self.placeholder, True, BLACK if self.text else GRAY)
        return None

    def draw(self, screen):
        current_text = self.text if self.text else self.placeholder
        self.txt_surface = FONT.render(current_text, True, BLACK if self.text else GRAY)
        
        self.rect.w = max(self.rect.w, self.txt_surface.get_width() + 10)
        
        pygame.draw.rect(screen, self.color, self.rect, 2)
        screen.blit(self.txt_surface, (self.rect.x + 5, self.rect.y + 5))

    def set_text(self, new_text):
        self.text = str(new_text)
        self.txt_surface = FONT.render(self.text if self.text else self.placeholder, True, BLACK if self.text else GRAY)
    
    def get_text(self):
        return self.text

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.color = GRAY if not enabled else (ACTIVE_COLOR if self.active else DARK_GRAY)
        if not enabled:
            self.active = False


class Button:
    def __init__(self, x, y, w, h, text, action=None, base_color=BLUE):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.action = action
        self.base_color = base_color
        self.text_color = WHITE
        self.hover_color = (min(255, base_color[0] + 30), min(255, base_color[1] + 30), min(255, base_color[2] + 30))
        #self.hover_color = (max(0, base_color[0] - 30), max(0, base_color[1] - 30), max(0, base_color[2] - 30)) # Más oscuro al pasar el cursor
        #self.click_color = (max(0, base_color[0] - 60), max(0, base_color[1] - 60), max(0, base_color[2] - 60)) # Aún más oscuro al presionar
        self.current_color = self.base_color
        self.enabled = True

    def draw(self, screen):
        if not self.enabled:
            pygame.draw.rect(screen, DARK_GRAY, self.rect)
        else:
            pygame.draw.rect(screen, self.current_color, self.rect)
        
        text_surf = FONT.render(self.text, True, self.text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)

    def handle_event(self, event):
        if not self.enabled:
            return False
        
        if event.type == pygame.MOUSEMOTION:
            if self.rect.collidepoint(event.pos):
                self.current_color = self.hover_color
            else:
                self.current_color = self.base_color
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                if self.action:
                    self.action()
                return True
        return False

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.current_color = self.base_color if enabled else DARK_GRAY

    def set_base_color(self, color):
        self.base_color = color
        self.current_color = color
        self.hover_color = (min(255, color[0] + 30), min(255, color[1] + 30), min(255, color[2] + 30))


# --- Funciones de Comunicación de Red ---

def send_message(sock, message_type, data=None):
    message_to_send = {"type": message_type}

    if message_type == "INITIAL_CLIENT_DATA":
        message_to_send = data # Data ya es el diccionario InicializacionCliente
    elif message_type == MSG_CHANGE_CAR_PROPERTIES:
        message_to_send = {
            "type": MSG_CHANGE_CAR_PROPERTIES,
            "velocity": data.get("velocity"),
            "tiempoDeEspera": data.get("tiempoDeEspera")
        }
    elif message_type == MSG_END_CONNECTION:
        message_to_send = {"type": MSG_END_CONNECTION}
    
    json_data = json.dumps(message_to_send)
    try:
        sock.sendall(json_data.encode('utf-8') + b'\n')
        return True
    except Exception as e:
        print(f"[!] Error enviando mensaje '{message_type}': {e}")
        return False

def network_listener(sock):
    global is_connected, assigned_client_id, all_cars_status, reconnect_attempts, reconnect_timer
    buffer = ""
    print("[*] Hilo de red iniciado, escuchando mensajes...")
    
    while is_connected:
        try:
            sock.settimeout(1.0) 
            data = sock.recv(4096).decode('utf-8')
            
            if not data:
                print("[*] Servidor desconectado o envió datos vacíos. Iniciando proceso de reconexión.")
                is_connected = False # Marcar como desconectado
                # No romper el bucle aquí, dejar que el bucle principal de Pygame maneje la desconexión
                # y posiblemente la reconexión.
                break 
            
            # Resetear intentos de reconexión y timer si recibimos datos
            reconnect_attempts = 0
            reconnect_timer = 0
            
            buffer += data
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if not line.strip():
                    continue

                try:
                    message = json.loads(line)
                    msg_type = message.get("tipo") # 'tipo' para mensajes del servidor al cliente

                    with car_status_lock:
                        if msg_type == MSG_CAR_STATUS:
                            car_id = message.get("clientId")
                            if car_id:
                                all_cars_status[car_id] = {
                                    "clientId": car_id,
                                    "position": message.get("position", 0),
                                    "direction": message.get("direction", "NONE"),
                                    "isCrossing": message.get("isCrossing", False),
                                    "state": message.get("state", "NONE")
                                }
                                get_unique_color(car_id) 

                        elif msg_type == MSG_CONNECTED:
                            assigned_client_id = message.get("clientId", "") # Capturar clientId del mensaje CONNECTED
                            print(f"[NET] Mensaje del Servidor: {msg_type} - Conexión establecida. ClientID: {assigned_client_id}")
                            
                        elif msg_type == MSG_CAR_START:
                            print(f"[NET] Mensaje del Servidor: {msg_type} - Coche comenzando a cruzar el puente. ClientID: {message.get('clientId')}")
                        elif msg_type == MSG_CAR_END:
                            print(f"[NET] Mensaje del Servidor: {msg_type} - Coche terminó de cruzar el puente. ClientID: {message.get('clientId')}")
                        elif msg_type == MSG_CHANGE_CAR_PROPERTIES_ACK:
                            print(f"[NET] Mensaje del Servidor: {msg_type} - Cambio de propiedades del coche confirmado.")
                        else:
                            if msg_type not in [MSG_CAR_STATUS, MSG_CONNECTED, MSG_CAR_START, MSG_CAR_END, MSG_CHANGE_CAR_PROPERTIES_ACK]:
                                print(f"[NET] Mensaje desconocido recibido: {message}")
                            
                except json.JSONDecodeError as e:
                    print(f"[NET][!] Error al decodificar JSON: {e}. Datos: '{line}'")
                except socket.timeout:
                    pass
                except Exception as e:
                    print(f"[NET][!] Error al procesar el mensaje: {e}")

        except ConnectionResetError:
            print("[*] Conexión reiniciada por el servidor (hilo de red). Iniciando proceso de reconexión.")
            is_connected = False
            break
        except socket.timeout:
            pass 
        except Exception as e:
            print(f"[!] Error general de red: {e}. Iniciando proceso de reconexión.")
            is_connected = False
            break
    print("[*] Hilo de red finalizado.")

# --- Funciones de Acciones de UI ---

def attempt_connection(velocity_input_box, tiempo_espera_input_box, direction_selected, is_reconnecting=False):
    """
    Intenta conectar o reconectar al servidor.
    is_reconnecting indica si es un intento de reconexión automática.
    """
    global client_socket, network_thread, is_connected, assigned_client_id, all_cars_status, reconnect_attempts, reconnect_timer

    if is_connected:
        print("Ya conectado.")
        return True # Ya conectado, no hay necesidad de intentar de nuevo

    try:
        velocity_text = velocity_input_box.get_text()
        tiempo_espera_text = tiempo_espera_input_box.get_text()

        if not velocity_text.isdigit() or not tiempo_espera_text.isdigit():
            if not is_reconnecting: # Solo mostrar el error si no es una reconexión automática
                print("[!] Entrada inválida: La velocidad y el tiempo de espera deben ser números enteros.")
            return False

        velocity = int(velocity_text)
        tiempo_espera = int(tiempo_espera_text)
        
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((HOST, PORT))
        print(f"[*] Conectado al servidor Go en {HOST}:{PORT}")
        is_connected = True
        
        # Enviar datos iniciales (o de reconexión si assigned_client_id ya existe)
        initial_data = {
            "direction": direction_selected,
            "velocity": velocity,
            "tiempoDeEspera": tiempo_espera,
            "clientId": assigned_client_id # Enviar el ID existente para reconectar
        }
        if not send_message(client_socket, "INITIAL_CLIENT_DATA", initial_data):
            is_connected = False
            client_socket.close()
            client_socket = None
            print("[!] Fallo al enviar datos iniciales/de reconexión, conexión cerrada.")
            return False

        if not is_reconnecting:
            print(f"[*] Datos iniciales enviados: Dir={direction_selected}, Vel={velocity}, Cooldown={tiempo_espera}")
        else:
            print(f"[*] Datos de reconexión enviados para ClientID: {assigned_client_id}. Dir={direction_selected}, Vel={velocity}, Cooldown={tiempo_espera}")

        # Iniciar o reiniciar el hilo de escucha de red DESPUÉS de conectar el socket
        # Si el hilo anterior aún está vivo, asegurar su terminación o gestionarlo.
        # En este caso, el `network_listener` se rompe si `is_connected` se vuelve `False`,
        # por lo que un nuevo hilo es lo más seguro.
        if network_thread and network_thread.is_alive():
            # Considerar una forma más robusta de detener el hilo antiguo si es necesario.
            # Por simplicidad, se asumirá que terminará pronto tras cambiar is_connected a False.
            pass
        
        network_thread = threading.Thread(target=network_listener, args=(client_socket,))
        network_thread.daemon = True
        network_thread.start()

        reconnect_attempts = 0 # Reiniciar intentos de reconexión al conectar exitosamente
        reconnect_timer = 0
        return True
        
    except ValueError:
        if not is_reconnecting:
            print("[!] Entrada inválida: La velocidad y el tiempo de espera deben ser enteros válidos.")
        return False
    except ConnectionRefusedError:
        if not is_reconnecting:
            print(f"[!] Error: Conexión rechazada. Asegúrate de que el servidor Go esté corriendo en {HOST}:{PORT}.")
        is_connected = False
        return False
    except Exception as e:
        if not is_reconnecting:
            print(f"[!] Ocurrió un error inesperado durante la conexión: {e}")
        is_connected = False
        return False

def connect_to_server_action(velocity_input_box, tiempo_espera_input_box, direction):
    """Acción manual de conexión."""
    global assigned_client_id
    assigned_client_id = "" # Asegurarse de que sea un nuevo cliente al conectar manualmente
    attempt_connection(velocity_input_box, tiempo_espera_input_box, direction, is_reconnecting=False)

def change_properties_action(velocity_input_box, tiempo_espera_input_box):
    if not is_connected:
        print("[!] No conectado al servidor.")
        return
    try:
        new_velocity_text = velocity_input_box.get_text()
        new_tiempo_de_espera_text = tiempo_espera_input_box.get_text()

        if not new_velocity_text.isdigit() or not new_tiempo_de_espera_text.isdigit():
            print("[!] Entrada inválida: La nueva velocidad y el tiempo de espera deben ser números enteros.")
            return

        new_velocity = int(new_velocity_text)
        new_tiempo_de_espera = int(new_tiempo_de_espera_text)
        
        send_message(client_socket, MSG_CHANGE_CAR_PROPERTIES, {
            "velocity": new_velocity,
            "tiempoDeEspera": new_tiempo_de_espera
        })
    except ValueError:
        print("[!] Entrada inválida para la nueva velocidad o tiempo de espera. Deben ser enteros.")

def end_connection_action():
    global is_connected, client_socket, assigned_client_id
    if not is_connected:
        print("[!] No conectado.")
        return
    
    print("[*] Enviando mensaje END_CONNECTION...")
    if send_message(client_socket, MSG_END_CONNECTION):
        print("[*] Mensaje END_CONNECTION enviado. Cerrando socket.")
    else:
        print("[!] Fallo al enviar mensaje END_CONNECTION, forzando cierre.")
    
    is_connected = False
    if client_socket:
        client_socket.close()
        client_socket = None
    assigned_client_id = "" # Resetear el ID del cliente al terminar conexión
    print("[*] Conexión del cliente finalizada.")

def simulate_disconnect_action():
    global is_connected, client_socket
    if not is_connected:
        print("[!] No conectado.")
        return
    
    print("[!] Simulando caída de internet (desconexión abrupta)...")
    is_connected = False
    if client_socket:
        client_socket.close()
        client_socket = None
    print("[*] Socket cerrado abruptamente. El servidor debería detectar la desconexión.")

# --- Función Principal de Pygame ---

def run_game(initial_velocity=None, initial_cooldown=None, initial_direction=None):
    global is_connected, assigned_client_id, all_cars_status, client_colors, color_index, reconnect_attempts, reconnect_timer

    direction_selected = initial_direction if initial_direction else DIRECTION_EAST_WEST
    
    def set_direction(direction):
        nonlocal direction_selected
        if not is_connected: # Solo permitir cambiar dirección si no está conectado
            if direction_selected != direction:
                direction_selected = direction
                print(f"Dirección seleccionada: {DIRECTION_LABELS.get(direction_selected)}")
            
            east_button.set_base_color(SELECTED_DIRECTION_COLOR if direction == DIRECTION_EAST_WEST else BLUE)
            west_button.set_base_color(SELECTED_DIRECTION_COLOR if direction == DIRECTION_WEST_EAST else BLUE)

    button_width = 150
    button_height = 40
    input_width = 200
    input_height = 40

    east_button = Button(WIDTH // 2 + 60, 150, button_width, button_height, DIRECTION_LABELS[DIRECTION_EAST_WEST], lambda: set_direction(DIRECTION_EAST_WEST), BLUE)
    west_button = Button(WIDTH // 2 + 80 + button_width + 10, 150, button_width, button_height, DIRECTION_LABELS[DIRECTION_WEST_EAST], lambda: set_direction(DIRECTION_WEST_EAST), BLUE)
    set_direction(direction_selected) # Inicializa el color del botón de dirección seleccionada

    velocity_input_box = InputBox(WIDTH // 2 + 30, 210, input_width, input_height, text=str(initial_velocity) if initial_velocity is not None else '10', is_numeric=True)
    tiempo_espera_input_box = InputBox(WIDTH // 2 + 30, 280, input_width, input_height, text=str(initial_cooldown) if initial_cooldown is not None else '5', is_numeric=True)
    
    input_boxes = [velocity_input_box, tiempo_espera_input_box]

    enter_bridge_button = Button(WIDTH // 2 + 30, 350, input_width + 10 + button_width, 50, "Entrar al Puente", 
                                 lambda: connect_to_server_action(velocity_input_box, tiempo_espera_input_box, direction_selected))

    change_properties_button = Button(WIDTH // 2 + 30, 350, input_width + 10 + button_width, 50, "Cambiar Propiedades", 
                                      lambda: change_properties_action(velocity_input_box, tiempo_espera_input_box), GREEN)
    
    terminate_connection_button = Button(WIDTH - 190, 20, 190, 40, "Terminar Conexión", end_connection_action, RED)
    simulate_drop_button = Button(WIDTH - 190, 70, 190, 40, "Simular Caída", simulate_disconnect_action, PURPUL)

    # Deshabilitar botones de control inicialmente si la conexión es automática
    if initial_velocity is not None and initial_cooldown is not None and initial_direction is not None:
        enter_bridge_button.set_enabled(False)
        east_button.set_enabled(False)
        west_button.set_enabled(False)
        velocity_input_box.set_enabled(False)
        tiempo_espera_input_box.set_enabled(False)

    change_properties_button.set_enabled(False)
    terminate_connection_button.set_enabled(False)
    simulate_drop_button.set_enabled(False)

    running = True
    clock = pygame.time.Clock()

    connection_status_message = "" # Mensaje a mostrar al usuario
    last_update_time = pygame.time.get_ticks() # Para control del timer de reconexión

    # Conexión automática si se pasaron argumentos
    if initial_velocity is not None and initial_cooldown is not None and initial_direction is not None:
        print("[*] Argumentos de inicio detectados. Intentando conexión automática...")
        if attempt_connection(velocity_input_box, tiempo_espera_input_box, direction_selected, is_reconnecting=False):
            print("[*] Conexión inicial automática exitosa.")
            connection_status_message = "Conectado automáticamente."
        else:
            print("[!] Fallo la conexión inicial automática. Operando en modo manual.")
            connection_status_message = "Desconectado (Fallo conexión automática)."
            # Habilitar los controles manuales si la conexión automática falla
            enter_bridge_button.set_enabled(True)
            east_button.set_enabled(True)
            west_button.set_enabled(True)
            velocity_input_box.set_enabled(True)
            tiempo_espera_input_box.set_enabled(True)

    while running:
        dt = (pygame.time.get_ticks() - last_update_time) / 1000.0 # Delta time en segundos
        last_update_time = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            # Manejo de clics de ratón para input boxes y botones
            if event.type == pygame.MOUSEBUTTONDOWN:
                if not is_connected: # Solo si no está conectado, para los botones de entrada
                    enter_bridge_button.handle_event(event)
                    east_button.handle_event(event)
                    west_button.handle_event(event)
                else: # Si está conectado, para los botones de control de propiedades/conexión
                    change_properties_button.handle_event(event)
                    terminate_connection_button.handle_event(event)
                    simulate_drop_button.handle_event(event)

                # Siempre manejar las cajas de texto, sin importar el estado de conexión
                for box in input_boxes:
                    if box.rect.collidepoint(event.pos):
                        box.active = True
                    else:
                        box.active = False
                    box.color = ACTIVE_COLOR if box.active else DARK_GRAY
            
            # Manejar eventos de teclado para input boxes
            for box in input_boxes:
                box.handle_event(event)

        # --- Lógica de reconexión automática ---
        if not is_connected and assigned_client_id != "" and reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            reconnect_timer += dt
            if reconnect_timer >= RECONNECT_DELAY:
                print(f"[*] Intentando reconexión ({reconnect_attempts + 1}/{MAX_RECONNECT_ATTEMPTS})...")
                connection_status_message = f"Intentando reconectar ({reconnect_attempts + 1}/{MAX_RECONNECT_ATTEMPTS})..."
                if attempt_connection(velocity_input_box, tiempo_espera_input_box, direction_selected, is_reconnecting=True):
                    print("[*] ¡Reconexión exitosa!")
                    connection_status_message = "Conectado."
                else:
                    reconnect_attempts += 1
                    reconnect_timer = 0 # Reiniciar el timer para el próximo intento
                    if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                        print("[!] Máximos intentos de reconexión alcanzados. Desconexión permanente.")
                        connection_status_message = "Desconectado. Reconexión fallida."
                        assigned_client_id = "" # Olvidar el ID si la reconexión falla permanentemente
        elif not is_connected and assigned_client_id == "":
            connection_status_message = "Desconectado."
        elif is_connected:
            connection_status_message = "Conectado."


        # --- Actualizar Estado de la UI ---
        if is_connected:
            east_button.set_enabled(False)
            west_button.set_enabled(False)
            # Asegurarse de que el color de los botones de dirección se restablezca
            east_button.set_base_color(BLUE)
            west_button.set_base_color(BLUE)

            velocity_input_box.set_enabled(True)
            tiempo_espera_input_box.set_enabled(True)

            enter_bridge_button.set_enabled(False)
            change_properties_button.set_enabled(True)
            terminate_connection_button.set_enabled(True)
            simulate_drop_button.set_enabled(True)
        else:
            east_button.set_enabled(True)
            west_button.set_enabled(True)
            set_direction(direction_selected) # Re-aplicar estado visual para los botones de dirección

            velocity_input_box.set_enabled(True)
            tiempo_espera_input_box.set_enabled(True)

            enter_bridge_button.set_enabled(True)
            change_properties_button.set_enabled(False)
            terminate_connection_button.set_enabled(False)
            simulate_drop_button.set_enabled(False)
            
            if assigned_client_id == "": # Solo limpiar si es una nueva conexión o reconexión fallida
                with car_status_lock:
                    all_cars_status.clear()
                    client_colors.clear()
                    color_index = 0


        # --- Dibujo ---
        SCREEN.fill(LIGHT_GRAY)

        # Dibujar panel izquierdo (Visualización del Puente)
        pygame.draw.rect(SCREEN, GRAY, (0, 0, WIDTH // 2, HEIGHT))
        
        # Puente
        bridge_y = HEIGHT // 2 - 20
        pygame.draw.rect(SCREEN, DARK_GRAY, (50, bridge_y, WIDTH // 2 - 100, 40))
        
        # Dibujar coches
        car_width = 30
        bridge_start_x = 50
        bridge_end_x = WIDTH // 2 - 50
        bridge_length_pixels = bridge_end_x - bridge_start_x - car_width

        active_crossing_car = None

        with car_status_lock:
            for car_id, car_data in all_cars_status.items():
                car_pos_logical = car_data["position"]
                car_direction = car_data["direction"]
                car_state = car_data["state"]
                car_color = get_unique_color(car_id)

                if car_state == CAR_STATE_CROSSING:
                    car_draw_y = bridge_y + 5

                    car_draw_x = 0
                    if car_direction == DIRECTION_WEST_EAST:
                        # De Oeste a Este, va de 0 a LENGTH_BRIDGE
                        car_draw_x = bridge_start_x + int((car_pos_logical / LENGTH_BRIDGE) * bridge_length_pixels)
                    elif car_direction == DIRECTION_EAST_WEST:
                        # De Este a Oeste, va de LENGTH_BRIDGE a 0 (visual en la pantalla)
                        car_draw_x = bridge_start_x + bridge_length_pixels - int((car_pos_logical / LENGTH_BRIDGE) * bridge_length_pixels)
                    
                    pygame.draw.rect(SCREEN, car_color, (car_draw_x, car_draw_y, car_width, 30))
                    
                    active_crossing_car = car_data # Esto solo tomará el último coche en la iteración si hay varios cruzando
                    pygame.draw.rect(SCREEN, BLACK, (car_draw_x, car_draw_y, car_width, 30), 2) # Borde negro para el coche activo


        # Mostrar información del coche que está cruzando
        current_car_info_y = 50
        if active_crossing_car and active_crossing_car['state'] == CAR_STATE_CROSSING:
            crossing_car_text1 = HIGHLIGHT_FONT.render(f"Coche Cruzando: {active_crossing_car['clientId']}", True, BLACK)
            SCREEN.blit(crossing_car_text1, (50, current_car_info_y))

            crossing_car_text2 = HIGHLIGHT_FONT.render(f"Dir: {DIRECTION_LABELS.get(active_crossing_car['direction'])}", True, BLACK)
            SCREEN.blit(crossing_car_text2, (50, current_car_info_y + 30))

            crossing_car_text3 = HIGHLIGHT_FONT.render(f"Pos: {active_crossing_car['position']} | Estado: {active_crossing_car['state']}", True, BLACK)
            SCREEN.blit(crossing_car_text3, (50, current_car_info_y + 60))
        else:
            no_car_text = FONT.render("Ningún coche cruzando", True, BLACK)
            SCREEN.blit(no_car_text, (50, current_car_info_y))
        
        # Mostrar estado de la conexión
        status_text = FONT.render(f"Estado: {connection_status_message}", True, BLACK)
        SCREEN.blit(status_text, (50, HEIGHT - 50))


        # Dibujar panel derecho (Formulario)
        pygame.draw.rect(SCREEN, WHITE, (WIDTH // 2, 0, WIDTH // 2, HEIGHT))
        
        title_surf = TITLE_FONT.render("Controles del Coche", True, BLACK)
        SCREEN.blit(title_surf, (WIDTH // 2 + 30, 30))

        client_id_surf = FONT.render(f"ID Cliente: {assigned_client_id if assigned_client_id else 'N/A'}", True, BLACK)
        SCREEN.blit(client_id_surf, (WIDTH // 2 + 30, 80))

        dir_label = FONT.render("Dirección:", True, BLACK)
        SCREEN.blit(dir_label, (WIDTH // 2 + 30, 120))
        east_button.draw(SCREEN)
        west_button.draw(SCREEN)
        
        vel_label = FONT.render("Velocidad:", True, BLACK)
        SCREEN.blit(vel_label, (WIDTH // 2 + 30, 190))
        velocity_input_box.draw(SCREEN)

        cooldown_label = FONT.render("Tiempo de Espera:", True, BLACK)
        SCREEN.blit(cooldown_label, (WIDTH // 2 + 30, 260))
        tiempo_espera_input_box.draw(SCREEN)

        # Los botones de control se dibujan según el estado de conexión
        if is_connected:
            change_properties_button.draw(SCREEN)
            terminate_connection_button.draw(SCREEN)
            simulate_drop_button.draw(SCREEN)
        else:
            enter_bridge_button.draw(SCREEN)
            # Los botones de dirección ya se dibujan antes de este 'else' y su estado se maneja con set_enabled

        pygame.display.flip()
        clock.tick(60)

    # Limpieza
    if client_socket:
        print("[*] Cerrando socket del cliente.")
        try:
            if is_connected: # Intentar enviar mensaje de fin solo si aún está "conectado" lógicamente
                send_message(client_socket, MSG_END_CONNECTION)
            client_socket.close()
        except Exception as e:
            print(f"[!] Error durante la limpieza del socket: {e}")
    
    if network_thread and network_thread.is_alive():
        print("[*] Esperando a que el hilo de red finalice...")
        # Darle tiempo al hilo para terminar. Un timeout es importante para no bloquear indefinidamente.
        network_thread.join(timeout=1.0) 
        if network_thread.is_alive():
            print("[!] El hilo de red no terminó limpiamente.")

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    initial_vel = None
    initial_cooldown = None
    initial_dir = None

    # sys.argv[0] es el nombre del script
    # Esperamos 3 argumentos adicionales: velocidad, tiempo_de_espera, direccion
    if len(sys.argv) == 4:
        try:
            initial_vel = int(sys.argv[1])
            initial_cooldown = int(sys.argv[2])
            initial_dir_str = sys.argv[3].upper() # Convertir a mayúsculas para comparar

            if initial_dir_str == "EAST_TO_WEST":
                initial_dir = DIRECTION_EAST_WEST
            elif initial_dir_str == "WEST_TO_EAST":
                initial_dir = DIRECTION_WEST_EAST
            else:
                raise ValueError("Dirección inválida. Use 'EAST_TO_WEST' o 'WEST_TO_EAST'.")

            print(f"[*] Parámetros de inicio por línea de comandos: Velocidad={initial_vel}, TiempoEspera={initial_cooldown}, Dirección={initial_dir}")
        except ValueError as e:
            print(f"[!] Error en los argumentos de línea de comandos: {e}")
            print("Uso: python cliente.py <velocidad> <tiempo_espera> <direccion>")
            print("Ejemplo: python cliente.py 15 7 EAST_TO_WEST")
            sys.exit(1) # Salir si hay un error en los argumentos

    run_game(initial_vel, initial_cooldown, initial_dir)