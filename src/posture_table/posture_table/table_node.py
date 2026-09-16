#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String
import serial

class TableNode(Node):
    def __init__(self):
        super().__init__('table_node')
        
        # Parámetros
        self.declare_parameter('port', '/dev/ttyACM0')
        self.declare_parameter('baud', 9600)
        
        port = self.get_parameter('port').value
        baud = self.get_parameter('baud').value
        
        # Publicador de distancia
        self.publisher_ = self.create_publisher(Float32, '/table/distance', 10)
        
        # Suscriptor de comandos
        self.subscription = self.create_subscription(
            String,
            '/table/command',
            self.command_callback,
            10
        )
        
        # Serie
        try:
            self.serial_port = serial.Serial(port, baud, timeout=1)
            self.get_logger().info(f'Puerto serie abierto: {port}')
        except serial.SerialException as e:
            self.get_logger().error(f'No se pudo abrir el puerto {port}: {e}')
            self.serial_port = None
        
        self.timer = self.create_timer(0.1, self.timer_callback)
    
    def timer_callback(self):
        if self.serial_port is None:
            return
        
        if self.serial_port.in_waiting > 0:
            try:
                line = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith('DIST:'):
                    try:
                        distance = float(line.split(':')[1])
                        msg = Float32()
                        msg.data = distance
                        self.publisher_.publish(msg)
                    except (ValueError, IndexError):
                        pass
            except Exception:
                pass
    
    def command_callback(self, msg: String):
        if self.serial_port is None:
            self.get_logger().warn('Puerto serie no disponible')
            return
        
        command = msg.data.upper()
        if command in ['UP', 'DOWN', 'STOP']:
            self.serial_port.write(f'{command}\n'.encode())
            self.get_logger().info(f'Comando enviado: {command}')
        else:
            self.get_logger().warn(f'Comando inválido: {command}')
    
    def destroy_node(self):
        if self.serial_port is not None:
            self.serial_port.close()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = TableNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
