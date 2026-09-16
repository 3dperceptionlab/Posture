import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String
import serial
import time

class SensorNode(Node):
    def __init__(self):
        super().__init__('arduino_sensor_node')
        
        self.ser = serial.Serial('/dev/ttyACM0', 9600, timeout=0)
        time.sleep(2)
        
        self.sensor_pub = self.create_publisher(Float32, '/arduino_sensor', 10)
        self.cmd_sub = self.create_subscription(String, '/arduino_cmd', self.cmd_callback, 10)
        
        self.get_logger().info('Sensor node iniciado')
    
    def cmd_callback(self, msg):
        comando = msg.data + '\n'
        self.ser.write(comando.encode())
        self.get_logger().info(f'Comando enviado: {msg.data}')
        time.sleep(0.2)
    
    def run(self):
        while rclpy.ok():
            if self.ser.in_waiting > 0:
                try:
                    linea = self.ser.readline().decode('utf-8').strip()
                    
                    # Formato: S:0.420V
                    if linea.startswith('S:') and linea.endswith('V'):
                        voltaje = float(linea[2:-1])
                        msg = Float32()
                        msg.data = voltaje
                        self.sensor_pub.publish(msg)
                except Exception as e:
                    pass
            
            rclpy.spin_once(self, timeout_sec=0)
            time.sleep(0.05)

def main(args=None):
    rclpy.init(args=args)
    node = SensorNode()
    node.run()
    node.destroy_node()

if __name__ == '__main__':
    main()
