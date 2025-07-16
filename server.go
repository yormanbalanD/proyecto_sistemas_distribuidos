package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"net"
	"os/exec"
	"strconv"
	"time"
)

const (
	LENGTH_BRIDGE  = 300
	MSG_CAR_STATUS = "CAR_STATUS"
	MSG_CAR_END    = "CAR_END"
	MSG_CAR_START  = "CAR_START"
	MSG_CONNECTED  = "CONNECTED"

	MSG_CHANGE_CAR_PROPERTIES     = "CHANGE_CAR_PROPERTIES"
	MSG_CHANGE_CAR_PROPERTIES_ACK = "CHANGE_CAR_PROPERTIES_ACK"

	MSG_END_CONNECTION = "END_CONNECTION"

	DIRECTION_NONE      = "NONE"
	DIRECTION_EAST_WEST = "EAST_TO_WEST"
	DIRECTION_WEST_EAST = "WEST_TO_EAST"
	CAR_STATE_WAITING   = "WAITING"
	CAR_STATE_CROSSING  = "CROSSING"
	CAR_STATE_COOLDOWN  = "COOLDOWN"
	SERVER_PORT         = 12345

	TIEMPO_MAXIMO_DESCONEXION = 30 // En segundos
)

// Una cola genérica para enteros
type CarQueue []*Car

// Enqueue añade un elemento al final de la cola
func (q *CarQueue) Enqueue(item *Car) {
	*q = append(*q, item)
}

// Dequeue remueve y retorna el primer elemento de la cola.
// Retorna un error si la cola está vacía.
func (q *CarQueue) Dequeue() (*Car, error) {
	if q.IsEmpty() {
		return nil, fmt.Errorf("la cola está vacía")
	}
	item := (*q)[0]
	*q = (*q)[1:] // Remueve el primer elemento
	return item, nil
}

// IsEmpty verifica si la cola está vacía
func (q *CarQueue) IsEmpty() bool {
	return len(*q) == 0
}

// Size retorna el número de elementos en la cola
func (q *CarQueue) Size() int {
	return len(*q)
}

// RemoveCarByID busca y elimina un coche de la cola por su ClientID.
// Retorna el coche removido y 'true' si se encontró y eliminó,
// o 'nil' y 'false' si el coche no se encontró en la cola.
func (q *CarQueue) RemoveCarByID(clientID string) (*Car, bool) {
	for i, car := range *q {
		if car.ClientID == clientID {
			// Coche encontrado. Lo eliminamos del slice.
			removedCar := car
			*q = append((*q)[:i], (*q)[i+1:]...) // Elimina el elemento en el índice 'i'

			fmt.Printf("Coche %s removido de la cola.\n", clientID)
			return removedCar, true
		}
	}

	return nil, false // Coche no encontrado
}

var EastToWestQueue CarQueue
var WestToEastQueue CarQueue

// Estructuras de mensajes enviados desde el servidor al cliente y viceversa

type MensajeStatusToClient struct {
	Tipo     string `json:"tipo"`
	ClientID string `json:"clientId"`
}

type MensajeChangeCarProperties struct {
	Velocity       int `json:"velocity"`
	TiempoDeEspera int `json:"tiempoDeEspera"`
}

type MensajeCarStatus struct {
	ClientID   string `json:"clientId"`
	Position   int    `json:"position"`
	Direction  string `json:"direction"`
	IsCrossing bool   `json:"isCrossing"`
	State      string `json:"state"` // WAITING, CROSSING
	Tipo       string `json:"tipo"`
}

type MessageToServer struct {
	Tipo string `json:"type"`
}

type InicializacionCliente struct {
	Direction      string `json:"direction"`
	Velocity       int    `json:"velocity"`
	TiempoDeEspera int    `json:"tiempoDeEspera"`
	ClientID       string `json:"clientId"`
}

type MensajeInicializacionToClient struct {
	ClientID       string `json:"clientId"`
	Direction      string `json:"direction"`
	Velocity       int    `json:"velocity"`
	State          string `json:"state"`
	TiempoDeEspera int    `json:"tiempoDeEspera"`
}

// Estructura de datos usada para almacenar los clientes en el servidor
type Car struct {
	ClientID              string
	Position              int
	Direction             string
	IsCrossing            bool
	State                 string // WAITING, CROSSING, COOLDOWN
	dec                   *json.Decoder
	enc                   *json.Encoder
	Velocity              int
	TiempoDeEspera        int
	conn                  net.Conn
	lastTimeConectionLost time.Time
	conectionLost         bool
}

// Tabla de clientes conectados al servidor
var tablaClientes = make(map[string]*Car)
var client_id_counter = 0

var current_car *Car
var is_occupied bool
var current_direction string

// Termina la conexión del cliente
func terminarConexion(car *Car) {
	fmt.Printf("El cliente %s ha finalizado la conexión.\n", car.ClientID)
	car.conn.Close()
	EastToWestQueue.RemoveCarByID(car.ClientID)
	WestToEastQueue.RemoveCarByID(car.ClientID)
	delete(tablaClientes, car.ClientID)
}

// Maneja la conexión del cliente con el servidor
func handleConnection(car *Car) {
	enc := car.enc
	dec := car.dec

	for {

		var mensaje MessageToServer
		err := dec.Decode(&mensaje)
		if err != nil {
			println("Error decodificando mensaje:", err)
			break
		}

		if mensaje.Tipo == MSG_CHANGE_CAR_PROPERTIES {
			var mensajeChangeCarProperties MensajeChangeCarProperties
			err := dec.Decode(&mensajeChangeCarProperties)
			if err != nil {
				println("Error decodificando mensaje de cambio de propiedades:", err)
				break
			}

			car.Velocity = mensajeChangeCarProperties.Velocity
			car.TiempoDeEspera = mensajeChangeCarProperties.TiempoDeEspera
			fmt.Printf("Cambio de propiedades del auto %s: Velocidad=%d, Tiempo de espera=%d\n", car.ClientID, car.Velocity, car.TiempoDeEspera)

			err = enc.Encode(MensajeStatusToClient{Tipo: MSG_CHANGE_CAR_PROPERTIES_ACK, ClientID: car.ClientID})
			if err != nil {
				println("Error al enviar mensaje de estado del car:", err)
			}

			continue
		}

		if mensaje.Tipo == MSG_END_CONNECTION {
			terminarConexion(car)
			break
		}
	}
}

// Guarda un cliente en la tabla de clientes y inicializa sus atributos
func conectarCliente(conn net.Conn) (*Car, error) {
	enc := json.NewEncoder(conn)
	dec := json.NewDecoder(conn)

	inicializacionCliente := InicializacionCliente{}

	err := dec.Decode(&inicializacionCliente)
	if err != nil {
		return nil, fmt.Errorf("Error decodificando mensaje de inicialización del cliente: %s", err)
	}

	var client_id string

	if inicializacionCliente.ClientID == "" {
		client_id = "Client-" + strconv.Itoa(client_id_counter)
		println("Nuevo cliente conectado:", client_id)
		println("Velocidad:", inicializacionCliente.Velocity)
		println("Dirección:", inicializacionCliente.Direction)
		println("Tiempo de espera:", inicializacionCliente.TiempoDeEspera)

		car := &Car{
			ClientID:              client_id,
			Position:              0,
			Direction:             inicializacionCliente.Direction,
			IsCrossing:            false,
			State:                 "WAITING",
			dec:                   dec,
			enc:                   enc,
			Velocity:              inicializacionCliente.Velocity,
			TiempoDeEspera:        inicializacionCliente.TiempoDeEspera,
			conn:                  conn,
			lastTimeConectionLost: time.Time{},
			conectionLost:         false,
		}

		tablaClientes[client_id] = car

		err = enc.Encode(MensajeStatusToClient{Tipo: MSG_CONNECTED, ClientID: client_id})
		if err != nil {
			println("Error al enviar mensaje de conexión:", err)
			conn.Close()
			return nil, err
		}

		if inicializacionCliente.Direction == DIRECTION_EAST_WEST {
			EastToWestQueue.Enqueue(car)
		} else {
			WestToEastQueue.Enqueue(car)
		}
		client_id_counter++

		return car, nil
	} else {

		client_id := inicializacionCliente.ClientID
		println("Cliente reconectado:", client_id)

		car, ok := tablaClientes[client_id]
		if !ok {
			return nil, fmt.Errorf("No se encuentra el cliente %s", client_id)
		}

		car.enc = enc
		car.dec = dec
		car.conn = conn
		car.lastTimeConectionLost = time.Time{}
		car.conectionLost = false

		err = enc.Encode(MensajeStatusToClient{Tipo: MSG_CONNECTED, ClientID: client_id})
		if err != nil {
			println("Error al enviar mensaje de conexión:", err)
			conn.Close()
			return nil, err
		}

		return car, nil
	}

}

// Marca la conexión con el cliente como conectado
func marcarConexionConCliente(car *Car) {
	car.conectionLost = false
	car.lastTimeConectionLost = time.Time{}
}

// Si el tiempo de desconexión excede 30 segundos, desconectar el cliente y devolvera false
func comprobarTiempoDeDesconexion(car *Car) bool {
	if !car.conectionLost {
		car.conectionLost = true
		car.lastTimeConectionLost = time.Now()
	} else {
		if time.Since(current_car.lastTimeConectionLost) > time.Second*TIEMPO_MAXIMO_DESCONEXION {
			println("El cliente", current_car.ClientID, "ha sido desconectado por exceso de tiempo.")
			terminarConexion(car)
			return false
		}
	}

	return true
}

func manejoDelPuente() {
	for {
		// Solo si no hay un coche cruzando
		if current_car == nil {
			var nextCar *Car

			// Prioridad 1: Coches en dirección actual si no hay ninguno
			if current_direction == DIRECTION_EAST_WEST && !EastToWestQueue.IsEmpty() {
				// Buscar un coche que no esté en cooldown
				for EastToWestQueue.Size() > 0 {
					tempCar, _ := EastToWestQueue.Dequeue()
					if tempCar.State == CAR_STATE_COOLDOWN {
						EastToWestQueue.Enqueue(tempCar) // Re-encolar si está en cooldown
					} else {
						nextCar = tempCar
						break
					}
				}
			} else if current_direction == DIRECTION_WEST_EAST && !WestToEastQueue.IsEmpty() {
				// Buscar un coche que no esté en cooldown
				for WestToEastQueue.Size() > 0 {
					tempCar, _ := WestToEastQueue.Dequeue()
					if tempCar.State == CAR_STATE_COOLDOWN {
						WestToEastQueue.Enqueue(tempCar) // Re-encolar si está en cooldown
					} else {
						nextCar = tempCar
						break
					}
				}
			}

			// Si no hay coches en la dirección actual o ya se procesaron los cooldowns,
			// intenta la dirección opuesta o la primera disponible
			if nextCar == nil {
				if !EastToWestQueue.IsEmpty() {
					for EastToWestQueue.Size() > 0 {
						tempCar, _ := EastToWestQueue.Dequeue()
						if tempCar.State == CAR_STATE_COOLDOWN {
							EastToWestQueue.Enqueue(tempCar)
						} else {
							nextCar = tempCar
							current_direction = DIRECTION_EAST_WEST // Cambiar la dirección del puente
							break
						}
					}
				}
				if nextCar == nil && !WestToEastQueue.IsEmpty() {
					for WestToEastQueue.Size() > 0 {
						tempCar, _ := WestToEastQueue.Dequeue()
						if tempCar.State == CAR_STATE_COOLDOWN {
							WestToEastQueue.Enqueue(tempCar)
						} else {
							nextCar = tempCar
							current_direction = DIRECTION_WEST_EAST // Cambiar la dirección del puente
							break
						}
					}
				}
			}

			current_car = nextCar // Asignar el coche seleccionado
			if current_car == nil {
				time.Sleep(time.Second * 1) // Esperar si no hay coches en ninguna cola
				continue
			}
		}

		// Cambiar los estados del auto
		current_car.State = CAR_STATE_CROSSING
		current_car.IsCrossing = true
		current_direction = current_car.Direction // Actualizar la dirección del puente

		is_occupied = true

		fmt.Printf("Puente ocupado por %s, en la dirección %s, a %d unidades por segundo\n", current_car.ClientID, current_direction, current_car.Velocity)

		seDesconectoElClientePrincipal := false

		// Enviar estado a todos los clientes
		for _, car := range tablaClientes {
			enc := car.enc
			err := enc.Encode(MensajeStatusToClient{Tipo: MSG_CAR_START, ClientID: current_car.ClientID})
			if err != nil {
				println("Error al enviar mensaje de estado al cliente ", car.ClientID, ":", err)

				res := comprobarTiempoDeDesconexion(car)

				if !res && car.ClientID == current_car.ClientID {
					seDesconectoElClientePrincipal = true
				}
			} else {
				marcarConexionConCliente(car)
			}
		}

		if seDesconectoElClientePrincipal {
			current_car = nil
			is_occupied = false
			continue
		}

		// Enviar estado a todos los clientes
		for _, car := range tablaClientes {
			enc := car.enc
			err := enc.Encode(MensajeCarStatus{Tipo: "CAR_STATUS", ClientID: current_car.ClientID, Position: 0, Direction: current_car.Direction, IsCrossing: true, State: CAR_STATE_CROSSING})
			if err != nil {
				println("Error al enviar mensaje de estado del auto al cliente ", car.ClientID, ":", err)

				res := comprobarTiempoDeDesconexion(car)

				if !res && car.ClientID == current_car.ClientID {
					seDesconectoElClientePrincipal = true
				}
			} else {
				marcarConexionConCliente(car)
			}
		}

		if seDesconectoElClientePrincipal {
			current_car = nil
			is_occupied = false
			continue
		}

		time.Sleep(time.Second * 1)

		conexionCerradaForzosamente := false

		for current_car.Position < LENGTH_BRIDGE {

			if tablaClientes[current_car.ClientID] == nil {
				println("No se encuentra el cliente", current_car.ClientID)
				conexionCerradaForzosamente = true
				break
			}

			x := min(current_car.Position+current_car.Velocity, LENGTH_BRIDGE)

			current_car.Position = x

			for _, car := range tablaClientes {
				enc := car.enc
				err := enc.Encode(MensajeCarStatus{Tipo: "CAR_STATUS", ClientID: current_car.ClientID, Position: x, Direction: current_car.Direction, IsCrossing: true, State: CAR_STATE_CROSSING})
				if err != nil {
					println("Error al enviar mensaje de estado del auto al cliente ", car.ClientID, ":", err)

					res := comprobarTiempoDeDesconexion(car)

					if !res && car.ClientID == current_car.ClientID {
						seDesconectoElClientePrincipal = true
					}
				} else {
					marcarConexionConCliente(car)
				}
			}

			if seDesconectoElClientePrincipal {
				break
			}

			fmt.Printf("Car %s crossing at %d\n", current_car.ClientID, current_car.Position)
			time.Sleep(time.Second * 1)
		}

		if seDesconectoElClientePrincipal {
			current_car = nil
			is_occupied = false
			continue
		}

		if conexionCerradaForzosamente {
			println("Conexión cerrada forzosamente por el cliente", current_car.ClientID)
			println("Car eliminada de la cola")
			current_car = nil
			is_occupied = false
			current_direction = DIRECTION_NONE
			continue
		}

		for _, car := range tablaClientes {
			enc := car.enc
			err := enc.Encode(MensajeCarStatus{Tipo: "CAR_STATUS", ClientID: current_car.ClientID, Position: LENGTH_BRIDGE, Direction: current_direction, IsCrossing: false, State: CAR_STATE_COOLDOWN})
			if err != nil {
				println("Error al enviar mensaje de estado del auto al cliente (2)", car.ClientID, ":", err)

				res := comprobarTiempoDeDesconexion(car)

				if !res && car.ClientID == current_car.ClientID {
					seDesconectoElClientePrincipal = true
				}
			} else {
				marcarConexionConCliente(car)
			}
		}

		if seDesconectoElClientePrincipal {
			current_car = nil
			is_occupied = false
			continue
		}

		// Cambiar los estados del auto
		current_car.Position = 0
		current_car.State = CAR_STATE_COOLDOWN
		current_car.IsCrossing = false

		for _, car := range tablaClientes {
			enc := car.enc
			err := enc.Encode(MensajeStatusToClient{Tipo: MSG_CAR_END, ClientID: current_car.ClientID})
			if err != nil {
				println("Error al enviar mensaje de finalizar estado de carro al cliente (2)", car.ClientID, ":", err)

				res := comprobarTiempoDeDesconexion(car)

				if !res && car.ClientID == current_car.ClientID {
					seDesconectoElClientePrincipal = true
				}
			} else {
				marcarConexionConCliente(car)
			}
		}

		if current_car.Direction == DIRECTION_EAST_WEST {
			current_car.Direction = DIRECTION_WEST_EAST
			current_direction = DIRECTION_WEST_EAST
			WestToEastQueue.Enqueue(current_car)
		} else {
			current_car.Direction = DIRECTION_EAST_WEST
			current_direction = DIRECTION_EAST_WEST
			EastToWestQueue.Enqueue(current_car)
		}

		carInCooldown := current_car
		time.AfterFunc(time.Second*time.Duration(carInCooldown.TiempoDeEspera), func() {
			carInCooldown.State = CAR_STATE_WAITING
		})
		fmt.Printf("El car %s ha sido cambiado de dirección y ahora mismo esta en espera\n", current_car.ClientID)

		is_occupied = false
		current_car = nil
	}
}

func main() {
	current_car = nil
	current_direction = DIRECTION_NONE
	is_occupied = false

	// Inicia el servidor
	server, err := net.Listen("tcp", ":"+strconv.Itoa(SERVER_PORT))
	if err != nil {
		panic(err)
	}

	println("Servidor escuchando en:", server.Addr().String())

	println("Iniciando el manejo del puente...")
	// Comienza el manejo del puente
	go manejoDelPuente()
	go crearClientesAleatorios(2)

	println("Iniciando la conexión con los clientes...")
	for {
		conn, err := server.Accept()
		if err != nil {
			panic(err)
		}

		car, err := conectarCliente(conn)

		if err != nil {
			println("Error al conectar cliente:", err)
			conn.Close() // Asegúrate de cerrar la conexión si la inicialización falla
			continue
		}

		go handleConnection(car)
	}
}

// Crea minNumClientes a (minNumClientes + 10) clientes aleatorios
func crearClientesAleatorios(minNumClientes int) {
	rand.Seed(time.Now().UnixNano())

	// Se generara entre min a (min + 10) clientes de forma aleatoria
	numeroDeClientes := rand.Intn(10) + minNumClientes

	time.Sleep(time.Second * 3)
	fmt.Printf("Generando %d clientes...\n", numeroDeClientes)

	for i := 0; i < numeroDeClientes; i++ {
		var cmd *exec.Cmd

		velocidadInicial := rand.Intn(40) + 20
		tiempoDeEsperaInicial := rand.Intn(10) + 2
		direccion := rand.Intn(2)

		if velocidadInicial < 0 || tiempoDeEsperaInicial < 0 || direccion < 0 {
			println("Error al generar cliente: Velocidad, tiempo de espera o dirección no válida")
			continue
		}

		var dir string

		if direccion == 0 {
			dir = DIRECTION_EAST_WEST
		} else {
			dir = DIRECTION_WEST_EAST
		}

		println("python client.py " + strconv.Itoa(velocidadInicial) + " " + strconv.Itoa(tiempoDeEsperaInicial) + " " + dir)

		cmd = exec.Command("python", "client.py", strconv.Itoa(velocidadInicial), strconv.Itoa(tiempoDeEsperaInicial), dir)
		err := cmd.Start()
		if err != nil {
			println("Error al iniciar cliente:", err)
			panic(err)
		}

		time.Sleep(time.Millisecond * 100)
	}
}
